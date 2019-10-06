from urlreader import URLReader
from urlreader.utils import callback, continue_runloop


reader = URLReader(timeout=0.001)
reader.fetch("https://www.amazon.com/", callback)

while not reader.done: continue_runloop()

