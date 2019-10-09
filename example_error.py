from urlreader import URLReader
from urlreader.utils import callback


reader = URLReader(timeout=1)
reader.fetch("https://www.doesnot-exist.forsure/", callback)

while not reader.done:
    reader.continue_runloop()
