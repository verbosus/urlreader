from urlreader import URLReader
from urlreader.utils import callback


urls = [
    'https://www.apple.com/',
    'https://www.amazon.com/',
    'https://www.wikipedia.com/',
    'https://www.ebay.com/',
    'https://www.microsoft.com/',
    'https://www.samsung.com/',
]

reader = URLReader()

for url in urls:
    reader.fetch(url, callback)

while not reader.done:
    reader.continue_runloop()
