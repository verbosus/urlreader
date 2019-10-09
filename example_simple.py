from urlreader import URLReader
from urlreader.utils import callback


reader = URLReader()
reader.fetch("https://www.apple.com/", callback)

while not reader.done:
    reader.continue_runloop()
