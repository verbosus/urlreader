import objc, os, hashlib, pathlib, threading, tempfile

from urllib.parse import urlparse, urlunparse, quote

from Foundation import NSObject, NSMutableData
from Foundation import NSFileManager, NSCachesDirectory, NSUserDomainMask
from Foundation import NSURL, NSURLSession, NSURLSessionConfiguration
from Foundation import NSURLRequest, NSURLRequestUseProtocolCachePolicy

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

    All URL reading operations execute in a background thread and return the
    URL contents to an asynchronous callback on the main thread.

    URLReader also comes with an optional, persistent, custom on-disk cache.
    NSURLSession and NSURLCache *almost* do everything we want. I spent a bit
    of time with both, and... almost. This project originated from an app that
    needs to download a bunch of data, store some of it on-disk so it’s
    available offline and treat the rest with normal HTTP caching policies.

    Which is all fine until we hit data that’s hosted on GitHub. GitHub is
    (understandably) quite aggressive with their cache headers for raw
    files (i.e. they set them Cache-Control: no-cache) and they don’t return
    the standard 200 HTTP response code, so NSURLSession and NSURLCache get
    confused and refuse to cache some of the data we get from there.
    """

    def __init__(self, timeout=10,
                 quote_url_path=True, force_https=False,
                 use_cache=False,
                 cache_location=CACHE_PATH):

        self._reader = _URLReader.alloc().init()
        self._reader.setTimeout_(timeout)
        self._quote_url_path = quote_url_path
        self._force_https = force_https
        self._cache_location = cache_location
        self._use_cache = use_cache

        if self._use_cache:
            self.cache = Cache(cache_location=self._cache_location)
            self._reader.setPersistentCache_(self.cache)

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

    def flush_cache(self):
        self.cache.flush()

    def invalidate_cache_for_url(self, url):
        if self._use_cache:
            self.cache.delete(self.process_url(url))

    def process_url(self, url):
        if self._quote_url_path:
            url = self.quote_url_path(url)
        if self._force_https:
            url = self.http2https_url(url)
        return url

    def fetch(self, url, callback, invalidate_cache=False):
        url = self.process_url(url)

        if invalidate_cache:
            self.invalidate_cache_for_url(url)

        self._reader.fetchURLOnBackgroundThread_withCallback_(
            NSURL.URLWithString_(url),
            callback
        )


class Cache(object):

    """A simple on-disk cache"""

    def __init__(self, cache_location=CACHE_PATH):
        self.cache_path = pathlib.Path(cache_location)

    def hash(self, key):
        return hashlib.sha1(key.encode('utf-8')).hexdigest()

    def flush(self):
        with threading.Lock():
            if self.cache_path.exists():
                _ = [x.unlink() for x in self.cache_path.iterdir() if x.is_file()]
                self.cache_path.rmdir()

    def _atomic_write(self, data, path):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            pathlib.Path(f.name).rename(path)

    def set(self, key, data):
        with threading.Lock():
            path = self.cache_path.joinpath(self.hash(key))
            if not self.cache_path.exists():
                self.cache_path.mkdir(parents=True)
            self._atomic_write(data, path)

    def get(self, key, default=None):
        path = self.cache_path.joinpath(self.hash(key))
        if path.exists():
            with open(path, 'rb') as f:
                data = f.read()
            return data
        return default

    def delete(self, key):
        with threading.Lock():
            path = self.cache_path.joinpath(self.hash(key))
            if path.exists():
                path.unlink()


class _URLReader(NSObject):

    """A light wrapper around NSURLSession & related APIs"""

    def init(self):
        self = objc.super(_URLReader, self).init()
        self._session = None
        self._timeout = None
        self._running_tasks = {}
        self._config = NSURLSessionConfiguration.defaultSessionConfiguration()
        self._config.setWaitsForConnectivity_(True)
        self._persistent_cache = None
        return self

    def setupSession(self):
        if self._timeout is not None:
            self._config.setTimeoutIntervalForResource_(self._timeout)
        self._session = NSURLSession.sessionWithConfiguration_delegate_delegateQueue_(
            self._config, self, None)

    def setTimeout_(self, timeout):
        self._timeout = timeout
        self.setupSession()

    def setPersistentCache_(self, cache):
        self._persistent_cache = cache

    def invalidateCacheForURL_(self, url):
        if self._persistent_cache:
            self._persistent_cache.delete(str(url))

    def requestForURL_(self, url):
        return NSURLRequest.requestWithURL_cachePolicy_timeoutInterval_(
            url, NSURLRequestUseProtocolCachePolicy, self._timeout
        )

    def fetchURLOnBackgroundThread_withCallback_(self, url, callback):
        request = self.requestForURL_(url)
        task = self._session.dataTaskWithRequest_(request)

        if self._persistent_cache is not None:
            cached_data = self._persistent_cache.get(str(url))

            if cached_data is not None:
                self._running_tasks[task] = (
                    cached_data,
                    callback
                )
                self.URLSession_task_didCompleteWithError_(
                    self._session, task, None)
                return

        # if we have a cache miss, actually execute the task
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

        if self._persistent_cache is not None:
            if self._persistent_cache.get(str(pre_redirects_url)) is None and \
                    error is None and len(_data):
                self._persistent_cache.set(str(pre_redirects_url), _data)

        if _callback is not None:
            # callAfter gets executed on the main thread
            # the argument types are: Python callable, NSURL, NSData, NSError
            callAfter(_callback, post_redirects_url, _data, error)

        del self._running_tasks[task]

    def done(self):
        return len(self._running_tasks) == 0

