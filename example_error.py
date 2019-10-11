from urlreader import URLReader
from urlreader.utils import callback


reader = URLReader(timeout=1, wait_until_done=True)
reader.fetch("https://www.doesnot-exist.forsure/", callback)
