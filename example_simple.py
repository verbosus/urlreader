from urlreader import URLReader
from urlreader.utils import callback


reader = URLReader(wait_until_done=True)
reader.fetch("https://www.apple.com/", callback)
