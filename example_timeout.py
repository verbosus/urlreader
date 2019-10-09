from urlreader import URLReader
from urlreader.utils import callback


reader = URLReader(timeout=0.001)
reader.fetch("https://www.amazon.com/", callback)

while not reader.done:
    reader.continue_runloop()
