from urlreader import URLReader
from urlreader.utils import callback


reader = URLReader(timeout=0.001, wait_until_done=True)
reader.fetch("https://www.amazon.com/", callback)
