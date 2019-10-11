# URLReader

URLReader is a wrapper around macOS’s NSURLSession, etc. 

## Scope & Limitations

URLReader originated from [an effort](https://github.com/robofont-mechanic/mechanic-2/pull/18) to improve the UI responsiveness of [Mechanic](https://robofontmechanic.com/), a package manager for the [RoboFont](https://www.robofont.com/) editor. Because of this original use-case, URLReader is meant to be used in PyObjC apps or scripts that need to download and possibly cache relatively small bits of additional data. 

## Basic usage

In its most basic form, URLReader takes a URL, fetches its contents in the background (so it won’t block your UI) and sends them back on the main thread to a callback you provide. The callback is a regular Python function with three arguments: `url` , `data` and `error` (of types `NSURL`, `NSData` and `NSError`). Like this:

```python
from urlreader import URLReader

def callback(url, data, error):
    if url and data and not error:
        print(f"Received {url} contents, {len(data)} bytes")

URLReader().fetch("http://example.org/", callback)
```

## Timeout

You can set a custom timeout for requests (which by default is 10 seconds):

```python
URLReader(timeout=2) # in seconds
```

Notice that this is the total response time, not how long it takes for the initial request to make it to the server. 

## Usage from scripts

You can use URLReader in synchronous mode for one-off scripts if you need to. It will block until the response is fully returned to your callback instead of calling it asynchronously like it normally would:

```python
URLReader(wait_until_done=True)
```

## Caching

By default, URLReader follows the caching policy set by the protocol, i.e. [NSURLRequestUseProtocolCachePolicy](https://developer.apple.com/documentation/foundation/nsurlrequestcachepolicy/nsurlrequestuseprotocolcachepolicy) which means it will do whatever the response HTTP caching headers tell it to do (if the request is HTTP.)

In some cases, however, you might want to cache the response so it’s available to your code even when offline. In these situations, URLReader switches the request cache policy to [NSURLRequestReturnCacheDataElseLoad](https://developer.apple.com/documentation/foundation/nsurlrequestcachepolicy/nsurlrequestreturncachedataelseload) which means it will first check its cache and return data from there no matter what the HTTP headers say. 

On top of the standard `NSURLRequestReturnCacheDataElseLoad` behavior, URLReader adds a little twist: if the original response required one or more redirects, which wouldn’t be cached therefore not available offline, NSURLCache isn’t able to fetch the response from its cache. URLReader adds a cache entry for the response URL *before the redirects* so they are fully accessible offline.

This all happens with the same code: 

```python 
URLReader(use_cache=True) # this switches on the caching mechanism described above
``` 

By default the cache will be written in `~/Library/Caches/<your app bundle identifier>` but that can be configured like this:

```python
URLReader(use_cache=True, cache_location="/my/cache/path") # cache_location can be either a string path or an NSURL
```

Once a URL is fetched by an URLReader with caching enabled, it stays in the cache indefinitely. You can force-reset a cached entry by setting `invalidate_cache=True` on the `fetch` method:

```python
reader.fetch(url, callback, invalidate_cache=True)
```

Or you can remove the cached entry without replacing it with a new one:

```python
reader.invalidate_cache_for_url(url)
```

Flushing the cache, removing all the cached entries, is also possible:

```python
reader.flush_cache()
```

## Tests

URLReader has a small test suite which spins a simple HTTP server in a separate process and runs against it. You can run it with the `tests.py` script in the main directory.

## And that’s it

Thanks for reading, hope this code is useful somehow.

---

URLReader was written by [Antonio Cavedoni](antonio@cavedoni.org) and is licensed under the terms of the [MIT License](https://github.com/verbosus/urlreader/blob/master/LICENSE).
