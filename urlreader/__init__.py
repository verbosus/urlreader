import objc
import logging

from urllib.parse import urlparse, urlunparse, quote

from Foundation import NSObject, NSRunLoop, NSDate
from Foundation import NSFileManager, NSCachesDirectory, NSUserDomainMask
from Foundation import NSURL, NSURLSession, NSURLSessionConfiguration
from Foundation import NSURLRequest, NSURLRequestUseProtocolCachePolicy
from Foundation import NSURLRequestReturnCacheDataElseLoad, NSURLCache
from Foundation import NSURLResponse, NSCachedURLResponse

from PyObjCTools.AppHelper import callAfter


logger = logging.getLogger('URLReader')


USER_CACHE_PATH, _ = NSFileManager.defaultManager().\
    URLForDirectory_inDomain_appropriateForURL_create_error_(
        NSCachesDirectory, NSUserDomainMask, None, True, None
    )
CACHE_PATH = USER_CACHE_PATH.\
    URLByAppendingPathComponent_isDirectory_('URLReader', True).relativePath()


def callback(url, data, error):
    """URLReader prototype callback

    By providing a function with the same signature as this to
    URLReader.fetch(), code can be notified when the background URL
    fetching operation has been completed and manipulate the resulting
    data. The callback will be called on the main thread.
    """
    raise NotImplementedError


class URLReader(object):
    """A wrapper around macOS’s NSURLSession, etc.

    All URL reading operations execute in the background and return the
    URL contents to an asynchronous callback on the main thread. Optionally,
    URLReader can be configured to use a persistent on-disk cache.
    """

    def __init__(self, timeout=10,
                 quote_url_path=True, force_https=False,
                 use_cache=False,
                 cache_location=CACHE_PATH,
                 wait_until_done=False):

        self._reader = _URLReader.alloc().init()
        self._reader.setTimeout_(timeout)
        self._quote_url_path = quote_url_path
        self._force_https = force_https
        self._cache_location = cache_location
        self._use_cache = use_cache
        self._wait_until_done = wait_until_done

        if self._use_cache:
            self._reader.setCacheAtPath_(cache_location)

    @property
    def done(self):
        return self._reader.done()

    def quote_url_path(self, url):
        u = urlparse(url)
        return urlunparse(u._replace(path=quote(u.path)))

    def http2https_url(self, url):
        u = urlparse(url)
        if u.scheme == 'http':
            return urlunparse(u._replace(scheme='https'))
        return url

    def process_url(self, url):
        if isinstance(url, NSURL):
            url = str(url)
        if self._quote_url_path:
            url = self.quote_url_path(url)
        if self._force_https:
            url = self.http2https_url(url)
        return NSURL.URLWithString_(url)

    def set_cache(self, url, data):
        url = self.process_url(url)
        return self._reader.setCachedData_forURL_(data, url)

    def get_cache(self, url):
        url = self.process_url(url)
        return self._reader.getCachedDataForURL_(url)

    def invalidate_cache_for_url(self, url):
        url = self.process_url(url)
        if self._use_cache:
            self._reader.invalidateCacheForURL_(url)

    def flush_cache(self):
        if self._use_cache:
            self._reader.flushCache()

    def continue_runloop(self):
        NSRunLoop.mainRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.01))

    def fetch(self, url, callback, invalidate_cache=False):
        url = self.process_url(url)

        if invalidate_cache:
            self.invalidate_cache_for_url(url)

        self._reader.fetchURL_withCallback_(url, callback)

        if self._wait_until_done:
            while not self.done:
                self.continue_runloop()


class _URLReader(NSObject):

    """A light wrapper around NSURLSession & related APIs"""

    def init(self):
        self = objc.super(_URLReader, self).init()
        self._session = None
        self._timeout = None
        self._callbacks = {}
        self._config = NSURLSessionConfiguration.defaultSessionConfiguration()
        self._config.setWaitsForConnectivity_(True)
        self._cache = None
        self._requestCachePolicy = NSURLRequestUseProtocolCachePolicy
        return self

    def setupSession(self):
        if self._timeout is not None:
            self._config.setTimeoutIntervalForResource_(self._timeout)
        if self._cache is not None:
            self._config.setURLCache_(self._cache)
            self._config.setRequestCachePolicy_(self._requestCachePolicy)
        self._session = NSURLSession.sessionWithConfiguration_(self._config)

    def setTimeout_(self, timeout):
        self._timeout = timeout
        self.setupSession()

    def setCacheAtPath_(self, path):
        self._cache = NSURLCache.alloc().\
            initWithMemoryCapacity_diskCapacity_diskPath_(
                5 * 1024 * 1024, 20 * 1024 * 1024, path
            )
        self._requestCachePolicy = NSURLRequestReturnCacheDataElseLoad
        self.setupSession()

    def makeCachedResponseWithData_forURL_(self, data, url):
        response = NSURLResponse.alloc().\
            initWithURL_MIMEType_expectedContentLength_textEncodingName_(
                url, 'application/octet-stream', len(data), 'utf-8'
            )
        return NSCachedURLResponse.alloc().\
            initWithResponse_data_(response, data)

    def getCachedDataForURL_(self, url):
        if self._cache:
            request = self.requestForURL_(url)
            cached_response = self._cache.cachedResponseForRequest_(request)
            if cached_response:
                return cached_response.data()

    def setCachedData_forURL_(self, data, url):
        if self._cache:
            response = self.makeCachedResponseWithData_forURL_(data, url)
            request = self.requestForURL_(url)
            self._cache.storeCachedResponse_forRequest_(response, request)

    def invalidateCacheForURL_(self, url):
        if self._cache:
            request = self.requestForURL_(url)
            self._cache.removeCachedResponseForRequest_(request)

    def flushCache(self):
        if self._cache:
            self._cache.removeAllCachedResponses()
        else:
            NSURLCache.sharedURLCache().removeAllCachedResponses()

    def requestForURL_(self, url):
        return NSURLRequest.requestWithURL_cachePolicy_timeoutInterval_(
            url, self._requestCachePolicy, self._timeout
        )

    def makeHandlerWithURL_(self, url):
        def handler(data, response, error):
            callback = self._callbacks[url]

            # if there is no data we return the original URL
            response_url = url

            if data and response:
                # always cache with the original request URL so even
                # if the response requires a redirect, like for raw
                # files on Github, we can still fulfill it offline
                self.setCachedData_forURL_(data, url)

                # if we have a response we pass the final URL after
                # the redirects, so a consumer can see it changed
                response_url = response.URL()

            callAfter(callback, response_url, data, error)
            del self._callbacks[url]
        return handler

    def fetchURL_withCallback_(self, url, callback):
        cachedData = self.getCachedDataForURL_(url)
        if cachedData:
            callAfter(callback, url, cachedData, None)
            return

        request = self.requestForURL_(url)
        handler = self.makeHandlerWithURL_(url)
        if url not in self._callbacks:
            self._callbacks[url] = callback
            task = self._session.\
                dataTaskWithRequest_completionHandler_(request, handler)
            task.resume()
        else:
            logger.error(f'{url} already being fetched')

    def done(self):
        return len(self._callbacks) == 0
