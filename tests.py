import time
import unittest

from multiprocessing import Process
from http.server import HTTPServer, BaseHTTPRequestHandler

from Foundation import NSThread, NSMutableData

from urlreader import URLReader, URLReaderError
from urlreader.utils import decode_data


MOCK_SERVER_ADDRESS = '127.0.0.1'
MOCK_SERVER_PORT = 9791
MOCK_SERVER_SCHEME = 'http'
MOCK_SERVER_URL = \
    f'{MOCK_SERVER_SCHEME}://{MOCK_SERVER_ADDRESS}:{MOCK_SERVER_PORT}'

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
        # cache for one hour
        self.send_header("Cache-Control", "max-age=3600")
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

    def setUp(self):
        reader = URLReader()
        reader._reader.flushCache()

    def tearDown(self):
        reader = URLReader()
        reader._reader.flushCache()


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
        reader = URLReader(wait_until_done=True)
        reader.fetch(
            MOCK_SERVER_URL,
            self._test_simple_url_fetch_callback,
        )

    def _test_simple_url_with_path_callback(self, url, data, error):
        self.assertEqual(decode_data(data), 'Hello, Ada!')

    def test_simple_url_with_path_fetch(self):
        reader = URLReader(wait_until_done=True)
        reader.fetch(MOCK_SERVER_URL + '/hello/Ada',
                     self._test_simple_url_with_path_callback)

    def _test_quoted_path_callback(self, url, data, error):
        self.assertEqual(decode_data(data), 'Hello, Mickey%20Mouse!')

    def test_quoted_path(self):
        reader = URLReader(wait_until_done=True)
        reader.fetch(MOCK_SERVER_URL + '/hello/Mickey Mouse',
                     self._test_quoted_path_callback)

    def _test_doubly_quoted_path_callback(self, url, data, error):
        self.assertEqual(decode_data(data), 'Hello, Mickey%2FMouse!')

    def test_doubly_quoted_path(self):
        reader = URLReader(wait_until_done=True)
        reader.fetch(MOCK_SERVER_URL + '/hello/Mickey%2FMouse',
                     self._test_doubly_quoted_path_callback)

    def _test_unquoted_path_callback(self, url, data, error):
        self.assertEqual(error.localizedDescription(), 'unsupported URL')

    def test_unquoted_path(self):
        reader = URLReader(quote_url_path=False, wait_until_done=True)
        reader.fetch(MOCK_SERVER_URL + '/hello/Mickey Mouse',
                     self._test_unquoted_path_callback)

    def _test_bogus_url_callback(self, url, data, error):
        # the call timed out and we have an error
        self.assertTrue(error is not None)

    def test_bogus_url(self):
        reader = URLReader(timeout=0.1, wait_until_done=True)
        reader.fetch("https://www.doesnot-exist.forsure-xxx/",
                     self._test_bogus_url_callback)

    def _test_timeout_request_callback(self, url, data, error):
        # the call timed out and we have an error...
        self.assertTrue(error is not None)
        # ...and no data
        self.assertEqual(data, None)

    def test_timeout_request(self):
        # set the timeout to some tiny amount
        reader = URLReader(timeout=0.2, wait_until_done=True)
        reader.fetch(MOCK_SERVER_URL + '/slow',
                     self._test_timeout_request_callback)

    def _test_multiple_urls_callback(self, url, data, error):
        self._multiple_urls_data.appendData_(data)
        self._multiple_urls_requested_loaded += 1
        if self._multiple_urls_requested_loaded == \
                self._multiple_urls_requested_count:
            data = decode_data(self._multiple_urls_data)
            self.assertTrue(
                'A' in data
                and 'B' in data
                and 'C' in data
                and 'D' in data
                and 'E' in data
                and 'F' in data
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
        while not reader.done:
            reader.continue_runloop()

    def test_redirect(self):
        # yes, of course you can also use a lambda as the callback
        URLReader(wait_until_done=True).fetch(
            MOCK_SERVER_URL + '/redirect',
            lambda url, data, error: self.assertEqual(
                str(url), MOCK_SERVER_URL + '/after-redirect'))


class CachingURLReaderTest(MockServerTest):

    def _test_cache_assert_0_callback(self, url, data, error):
        self.assertEqual('0', decode_data(data))

    def _test_cache_assert_1_callback(self, url, data, error):
        self.assertEqual('1', decode_data(data))

    def _test_cache_assert_2_callback(self, url, data, error):
        self.assertEqual('2', decode_data(data))

    def _test_server_reset_count(self):
        # reset the test server count
        reader = URLReader(wait_until_done=True)
        reader.fetch(MOCK_SERVER_URL + '/count/reset',
                     self._test_cache_assert_0_callback)

    def test_transient_cache(self):
        reader = URLReader(wait_until_done=True)
        reader.fetch(MOCK_SERVER_URL + '/count/increment',
                     self._test_cache_assert_1_callback)

        # This second call won’t actually hit the server
        # because it’s respecting the HTTP caching headers.
        # Thanks, NSURLRequestUseProtocolCachePolicy!
        reader.fetch(MOCK_SERVER_URL + '/count/increment',
                     self._test_cache_assert_1_callback)

        # bust the cache again...
        reader._reader.flushCache()
        # ...so the third request will hit the server
        reader.fetch(MOCK_SERVER_URL + '/count/increment',
                     self._test_cache_assert_2_callback)

        # reset the count at the end of the test
        self._test_server_reset_count()

    def test_persistent_cache(self):
        reader = URLReader(
            use_cache=True,
            cache_location=TEMP_URLREADER_CACHE,
            wait_until_done=True,
        )

        # hit the server, first
        reader.fetch(MOCK_SERVER_URL + '/count/increment',
                     self._test_cache_assert_1_callback)

        # this second call won’t actually hit the server
        # because it’s coming from the persistent cache
        reader.fetch(MOCK_SERVER_URL + '/count/increment',
                     self._test_cache_assert_1_callback)

        # this will hit the server and should return 1
        # because the previous increment call didn’t actually execute
        reader.fetch(MOCK_SERVER_URL + '/count/current',
                     self._test_cache_assert_1_callback)

        # this invalidates the cache, and thus hits the server
        reader.fetch(MOCK_SERVER_URL + '/count/increment',
                     self._test_cache_assert_2_callback,
                     invalidate_cache=True)

        self._test_server_reset_count()
        reader.flush_cache()

    def test_cache_invalidate_existing_url(self):
        TEST_URL = f"{MOCK_SERVER_URL}/hello/A"

        reader = URLReader(
            use_cache=True,
            cache_location=TEMP_URLREADER_CACHE,
            wait_until_done=True,
        )

        # it’s not cached yet
        self.assertEqual(reader.get_cache(TEST_URL), None)

        # fetch and cache it
        reader.fetch(
            TEST_URL,
            lambda url, data, error:
            self.assertEqual('Hello, A!', decode_data(data)))

        # it’s in the cache
        self.assertEqual('Hello, A!', decode_data(reader.get_cache(TEST_URL)))

        # invalidate the cache
        reader.invalidate_cache_for_url(TEST_URL)

        # it’s no longer in the cache
        self.assertEqual(reader.get_cache(TEST_URL), None)

        reader.flush_cache()

    def test_cache_invalidate_non_existing_url(self):
        NON_EXISTING_URL = 'http://non-existing.example.org/'
        reader = URLReader(
            use_cache=True,
            cache_location=TEMP_URLREADER_CACHE,
            wait_until_done=True,
        )
        self.assertEqual(reader.get_cache(NON_EXISTING_URL), None)

        # Invalidating a non-existing URL shouldn’t raise any exceptions
        reader.invalidate_cache_for_url(NON_EXISTING_URL)
        reader.flush_cache()

    def test_cache_invalidate_on_none(self):
        reader = URLReader(
            use_cache=True,
            cache_location=TEMP_URLREADER_CACHE,
            wait_until_done=True,
        )

        # this should raise
        with self.assertRaises(URLReaderError):
            reader.invalidate_cache_for_url(None)
        reader.flush_cache()


class OfflineURLReaderTest(unittest.TestCase):

    """Offline test suite

    These tests should still function even if there is no HTTP server,
    because the responses are coming from the cache.
    """

    NON_EXISTENT_URL = f'{MOCK_SERVER_URL}/non-existent'
    NON_EXISTENT_CONTENTS = b'This URL does not exist'

    HTTPS_URL = f'https://{MOCK_SERVER_ADDRESS}:{MOCK_SERVER_PORT}/https'
    HTTPS_CONTENTS = b'Hello, https'

    def setUp(self):
        self.reader = URLReader(
            timeout=2,
            use_cache=True,
            cache_location=TEMP_URLREADER_CACHE,
            wait_until_done=True,
        )
        self.reader.flush_cache()

        # set the cache to respond to an arbitrary, non-existent URL
        self.reader.set_cache(
            OfflineURLReaderTest.NON_EXISTENT_URL,
            OfflineURLReaderTest.NON_EXISTENT_CONTENTS)
        # verify the cache is actually set
        self.assertEqual(
            self.reader.get_cache(OfflineURLReaderTest.NON_EXISTENT_URL),
            OfflineURLReaderTest.NON_EXISTENT_CONTENTS)

        # set the cache to respond to an https URL
        self.reader.set_cache(
            OfflineURLReaderTest.HTTPS_URL,
            OfflineURLReaderTest.HTTPS_CONTENTS)
        # verify the cache is actually set
        self.assertEqual(
            self.reader.get_cache(OfflineURLReaderTest.HTTPS_URL),
            OfflineURLReaderTest.HTTPS_CONTENTS)

    def tearDown(self):
        self.reader.flush_cache()

    def test_offline_cache(self):
        # this shouldn’t even hit the server
        self.reader.fetch(
            OfflineURLReaderTest.NON_EXISTENT_URL,
            lambda url, data, error: self.assertEqual(
                OfflineURLReaderTest.NON_EXISTENT_CONTENTS, data))

    def test_force_https(self):
        # Okay, so here’s a roundabout way of testing that our force_https
        # does what we want it to do. Instead of running a full SSL server
        # in Python, which is possible but a little cumbersome, we populate
        # the persistent cache with an entry for the http*s* server URL, then
        # we ask our URLReader to read the http URL but with force_https,
        # which will promote http to https, which will make it hit the cache!
        # I know... right?!
        self.reader._force_https = True

        # this is an http URL, right?
        self.reader.fetch(
            f'{MOCK_SERVER_URL}/https',
            lambda url, data, error: self.assertEqual(
                OfflineURLReaderTest.HTTPS_CONTENTS, data)
        )


if __name__ == '__main__':
    unittest.main()
