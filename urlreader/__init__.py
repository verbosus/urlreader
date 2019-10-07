import objc

from urllib.parse import urlparse, urlunparse, quote

from Foundation import NSObject, NSMutableData
from Foundation import NSRunLoop, NSDate
from Foundation import NSFileManager, NSCachesDirectory, NSUserDomainMask
from Foundation import NSURL, NSURLSession, NSURLSessionConfiguration
from Foundation import NSURLRequest, NSURLRequestUseProtocolCachePolicy
from Foundation import NSURLRequestReturnCacheDataElseLoad, NSURLCache
from Foundation import NSURLResponse, NSCachedURLResponse

from PyObjCTools.AppHelper import callAfter


USER_CACHE_PATH, _ = NSFileManager.defaultManager().\
    URLForDirectory_inDomain_appropriateForURL_create_error_(
        NSCachesDirectory, NSUserDomainMask, None, True, None
    )
CACHE_PATH = USER_CACHE_PATH.\
    URLByAppendingPathComponent_isDirectory_('URLReader', True).relativePath()


def callback(url, data, error):
    """URLReader prototype callback

    By providing a function with the same signature as this to URLReader.fetch(),
    code can be notified when the background URL fetching operation has been
    completed and manipulate the resulting data. The callback will be called
    on the main thread.
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

        self._reader.fetchURLOnBackgroundThread_withCallback_(url, callback)

        if self._wait_until_done:
            while not self.done: self.continue_runloop()


class _URLReader(NSObject):

    """A light wrapper around NSURLSession & related APIs"""

    def init(self):
        self = objc.super(_URLReader, self).init()
        self._session = None
        self._timeout = None
        self._running_tasks = {}
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
        self._session = NSURLSession.sessionWithConfiguration_delegate_delegateQueue_(
            self._config, self, None)

    def setTimeout_(self, timeout):
        self._timeout = timeout
        self.setupSession()

    def setCacheAtPath_(self, path):
        self._cache = NSURLCache.alloc().\
            initWithMemoryCapacity_diskCapacity_diskPath_(
                0, 20 * 1024 * 1024, path
            )
        self._requestCachePolicy = NSURLRequestReturnCacheDataElseLoad
        self.setupSession()

    def makeCachedResponseWithData_forURL_(self, data, url):
        request = self.requestForURL_(url)
        response = NSURLResponse.alloc().\
            initWithURL_MIMEType_expectedContentLength_textEncodingName_(
                url, 'application/octet-stream', len(data), 'utf-8'
            )
        return NSCachedURLResponse.alloc().\
            initWithResponse_data_(response, data)

    def getCachedDataForURL_(self, url):
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

    def fetchURLOnBackgroundThread_withCallback_(self, url, callback):
        request = self.requestForURL_(url)
        task = self._session.dataTaskWithRequest_(request)

        if self._cache:
            cached_data = self.getCachedDataForURL_(url)
            if cached_data:
                self.completeWithCallback_URL_data_error_(
                    callback, url, cached_data, None
                )
                return

        self._running_tasks[task] = (
            NSMutableData.alloc().init(),
            callback
        )
        task.resume()

    def URLSession_dataTask_didReceiveData_(self, session, task, data):
        _data, _ = self._running_tasks[task]
        _data.appendData_(data)

    def URLSession_task_didCompleteWithError_(self, session, task, error):
        _data, _callback = self._running_tasks[task]

        pre_redirects_url = task.originalRequest().URL()
        post_redirects_url = task.currentRequest().URL()

        if self._cache:
            cached_response = self.makeCachedResponseWithData_forURL_(
                _data, pre_redirects_url)
            self._cache.storeCachedResponse_forRequest_(
                cached_response,
                task.originalRequest()
            )

        if _callback is not None:
            self.completeWithCallback_URL_data_error_(
                _callback, post_redirects_url, _data, error
            )

        del self._running_tasks[task]

    def completeWithCallback_URL_data_error_(self, callback, url, data, error):
        # callAfter gets executed on the main thread
        # the argument types are: Python callable, NSURL, NSData, NSError
        callAfter(callback, url, data, error)

    def done(self):
        return len(self._running_tasks) == 0

