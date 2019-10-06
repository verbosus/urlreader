from urlreader import URLReader
from urlreader.utils import callback, continue_runloop


reader = URLReader()
reader.fetch("https://www.apple.com/", callback)

while not reader.done: continue_runloop()

