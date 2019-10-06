import unittest, time

from multiprocessing import Process
from http.server import HTTPServer, BaseHTTPRequestHandler

from Foundation import NSThread, NSMutableData

from urlreader import URLReader, Cache
from urlreader.utils import callback, decode_data, continue_runloop


MOCK_SERVER_ADDRESS = '127.0.0.1'
MOCK_SERVER_PORT = 9791
MOCK_SERVER_SCHEME = 'http'
MOCK_SERVER_URL = f'{MOCK_SERVER_SCHEME}://{MOCK_SERVER_ADDRESS}:{MOCK_SERVER_PORT}'

TEMP_URLREADER_CACHE = '/tmp/URLReaderCache'


class MockServer(BaseHTTPRequestHandler):

    """A quick HTTP server to test URLReader"""

    count = 0

    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(301)
            self.send_header("Location", "/after-redirect")
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Cache-Control", "max-age=3600") # cache for one hour
        self.end_headers()

        if self.path == '/':
            self.wfile.write(b'Hello, world')
        elif self.path == '/slow':
            time.sleep(2)
            self.wfile.write(b'Slow response')
        elif self.path == '/count/reset':
            MockServer.count = 0
            self.wfile.write(f'{MockServer.count}'.encode('utf-8'))
        elif self.path == '/count/increment':
            MockServer.count += 1
            self.wfile.write(f'{MockServer.count}'.encode('utf-8'))
        elif self.path == '/count/current':
            self.wfile.write(f'{MockServer.count}'.encode('utf-8'))
        elif self.path == '/after-redirect':
            self.wfile.write(f'You’ve been redirected'.encode('utf-8'))
        else:
            bits = self.path[1:].split('/')
            if bits[0] == 'hello' and len(bits) == 2:
                name = bits[1]
                self.wfile.write(f'Hello, {name}!'.encode('utf-8'))

    # silence logging for test purposes
    def log_message(self, *args): pass


class MockServerTest(unittest.TestCase):

    server = None

    @classmethod
    def setUpClass(cls):
        # make an HTTP server and run it in another process
        def run_test_http_server():
            server_address = (MOCK_SERVER_ADDRESS, MOCK_SERVER_PORT)
            httpd = HTTPServer(server_address, MockServer)
            httpd.serve_forever()

        cls.server = Process(target=run_test_http_server)
        cls.server.daemon = True
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        # tear down the server
        if cls.server.is_alive():
            cls.server.terminate()


class URLReaderTest(MockServerTest):

    """Main test suite, executes against MockServer"""

    def _test_simple_url_fetch_callback(self, url, data, error):
        # callbacks always execute on the main thread
        self.assertTrue(NSThread.currentThread().isMainThread())

        # the URL is the correct one
        self.assertTrue(url, MOCK_SERVER_URL)

        # we got some data back
        self.assertEqual(decode_data(data), 'Hello, world')

    def test_simple_url_fetch(self):
        reader = URLReader()
        reader.fetch(MOCK_SERVER_URL, self._test_simple_url_fetch_callback)
        while not reader.done: continue_runloop()

    def _test_simple_url_with_path_callback(self, url, data, error):
        self.assertEqual(decode_data(data), 'Hello, Ada!')

    def test_simple_url_with_path_fetch(self):
        reader = URLReader()
        reader.fetch(MOCK_SERVER_URL + '/hello/Ada', 
            self._test_simple_url_with_path_callback)
        while not reader.done: continue_runloop()

    def _test_quoted_path_callback(self, url, data, error):
        self.assertEqual(decode_data(data), 'Hello, Mickey%20Mouse!')

    def test_quoted_path(self):
        reader = URLReader()
        reader.fetch(MOCK_SERVER_URL + '/hello/Mickey Mouse', 
            self._test_quoted_path_callback)
        while not reader.done: continue_runloop()

    def _test_unquoted_path_callback(self, url, data, error):
        self.assertEqual(error.localizedDescription(), 'unsupported URL')

    def test_unquoted_path(self):
        reader = URLReader(quote_url_path=False)
        reader.fetch(MOCK_SERVER_URL + '/hello/Mickey Mouse', 
            self._test_unquoted_path_callback)
        while not reader.done: continue_runloop()

    def _test_bogus_url_callback(self, url, data, error):
        # the call timed out and we have an error
        self.assertTrue(error is not None)

    def test_bogus_url(self):
        reader = URLReader(timeout=0.1)
        reader.fetch("https://www.doesnot-exist.forsure-xxx/",
            self._test_bogus_url_callback)
        while not reader.done: continue_runloop()

    def _test_timeout_request_callback(self, url, data, error):
        # the call timed out and we have an error...
        self.assertTrue(error is not None)
        # ...and no data
        self.assertEqual(len(data), 0)

    def test_timeout_request(self):
        # set the timeout to some tiny amount
        reader = URLReader(timeout=0.2)
        reader.fetch(MOCK_SERVER_URL + '/slow', 
            self._test_timeout_request_callback)
        while not reader.done: continue_runloop()

    def _test_multiple_urls_callback(self, url, data, error):
        self._multiple_urls_data.appendData_(data)
        self._multiple_urls_requested_loaded += 1
        if self._multiple_urls_requested_loaded == self._multiple_urls_requested_count:
            data = decode_data(self._multiple_urls_data)
            self.assertTrue(
                'A' in data and \
                'B' in data and \
                'C' in data and \
                'D' in data and \
                'E' in data and \
                'F' in data
            )

    def test_multiple_urls(self):
        urls = [
            MOCK_SERVER_URL + '/hello/A',
            MOCK_SERVER_URL + '/hello/B',
            MOCK_SERVER_URL + '/hello/C',
            MOCK_SERVER_URL + '/hello/D',
            MOCK_SERVER_URL + '/hello/E',
            MOCK_SERVER_URL + '/hello/F',
        ]

        self._multiple_urls_requested_count = len(urls)
        self._multiple_urls_data = NSMutableData.alloc().init()
        self._multiple_urls_requested_loaded = 0

        reader = URLReader()
        for url in urls:
            reader.fetch(url, self._test_multiple_urls_callback)
        while not reader.done: continue_runloop()


class CachingURLReaderTest(MockServerTest):

    def _test_cache_assert_0_callback(self, url, data, error):
        self.assertEqual('0', decode_data(data))

    def _test_cache_assert_1_callback(self, url, data, error):
        self.assertEqual('1', decode_data(data))

    def _test_cache_assert_2_callback(self, url, data, error):
        self.assertEqual('2', decode_data(data))

    def _test_server_reset_count(self):
        # reset the test server count
        reader = URLReader()
        reader.fetch(MOCK_SERVER_URL + '/count/reset',
            self._test_cache_assert_0_callback)
        while not reader.done: continue_runloop()

    def test_transient_cache(self):
        # first, test the cache
        reader = URLReader()
        reader.fetch(MOCK_SERVER_URL + '/count/increment',
            self._test_cache_assert_1_callback)
        while not reader.done: continue_runloop()

        # This second call won’t actually hit the server
        # because it’s respecting the HTTP caching headers.
        # Thanks, NSURLRequestUseProtocolCachePolicy!
        reader.fetch(MOCK_SERVER_URL + '/count/increment',
            self._test_cache_assert_1_callback)
        while not reader.done: continue_runloop()
        self._test_server_reset_count()

    def test_persistent_cache(self):
        reader = URLReader(
            use_cache=True,
            cache_location=TEMP_URLREADER_CACHE,
        )

        # hit the server, first
        reader.fetch(MOCK_SERVER_URL + '/count/increment',
            self._test_cache_assert_1_callback,
        )
        while not reader.done: continue_runloop()

        # this second call won’t actually hit the server
        # because it’s coming from the persistent cache
        reader.fetch(MOCK_SERVER_URL + '/count/increment',
            self._test_cache_assert_1_callback,
        )
        while not reader.done: continue_runloop()

        # this will hit the server and should return 1 
        # because the previous increment call didn’t actually execute
        reader.fetch(MOCK_SERVER_URL + '/count/current',
            self._test_cache_assert_1_callback,
        )
        while not reader.done: continue_runloop()

        # this would hit the server but doesn’t
        # it’s getting caught by the standard HTTP caching machinery
        reader.fetch(MOCK_SERVER_URL + '/count/increment',
            self._test_cache_assert_1_callback,
            invalidate_cache=True,
        )
        while not reader.done: continue_runloop()

        self._test_server_reset_count()
        reader.flush_cache()

    def _redirect_with_persistent_cache_callback(self, url, data, error):
        self.assertEqual(str(url), MOCK_SERVER_URL + '/after-redirect')
        self.assertEqual('You’ve been redirected', decode_data(data))

    def test_redirect_with_persistent_cache(self):
        reader = URLReader(
            use_cache=True,
            cache_location=TEMP_URLREADER_CACHE,
        )
        reader.fetch(MOCK_SERVER_URL + '/redirect',
            self._redirect_with_persistent_cache_callback)
        reader.flush_cache()


class OfflineURLReaderTest(unittest.TestCase):

    """Offline test suite

    These tests should still function even if there is no HTTP server,
    because the responses are coming from the cache.
    """

    def _test_offline_cache_callback(self, url, data, error):
        self.assertTrue('hello' in decode_data(data))

    def test_offline_cache(self):
        reader = URLReader(
            use_cache=True,
            cache_location=TEMP_URLREADER_CACHE,
        )

        # normally, /count/increment would return some number
        # but we make it return a string instead to make sure
        # this value comes from our cache
        reader.cache.set(MOCK_SERVER_URL + '/count/increment', b'hello')

        reader.fetch(MOCK_SERVER_URL + '/count/increment',
            self._test_offline_cache_callback,
        )
        while not reader.done: continue_runloop()
        reader.cache.flush()

    def _test_force_https_callback(self, url, data, error):
        self.assertEqual('Hello, https', decode_data(data))

    def test_force_https(self):
        # Okay, so here’s a roundabout way of testing that our force_https
        # does what we want it to do. Instead of running a full SSL server
        # in Python, which is possible but a little cumbersome, we populate
        # the persistent cache with an entry for the httpS server URL, then 
        # we ask our URLReader to read the http URL but with force_https, 
        # which will promote http to https, which will make it hit the cache!
        reader = URLReader(
            force_https=True,
            use_cache=True,
            cache_location=TEMP_URLREADER_CACHE
        )
        reader.cache.set(
            f'https://{MOCK_SERVER_ADDRESS}:{MOCK_SERVER_PORT}/',
            b'Hello, https',
        )

        # this is an http URL, right? 
        reader.fetch(MOCK_SERVER_URL + '/',
            self._test_force_https_callback,
        )
        while not reader.done: continue_runloop()
        reader.cache.flush()


class CacheTest(unittest.TestCase):

    def setUp(self):
        self.cache = Cache(
            cache_location=TEMP_URLREADER_CACHE)

    def tearDown(self):
        self.cache.flush()

    def test_cache_hit(self):
        self.cache.set('foo', b'some data')
        self.assertEqual(self.cache.get('foo'), b'some data')

    def test_cache_miss(self):
        self.assertEqual(self.cache.get('foo'), None)


if __name__ == '__main__':
    unittest.main()

