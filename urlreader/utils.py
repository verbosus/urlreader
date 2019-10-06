from urllib.parse import urlparse

from Foundation import NSRunLoop, NSDate
from Foundation import NSString, NSUTF8StringEncoding


def callback(url, data, error):
    if error is not None:
        print(error)
    else:
        print(f"{urlparse(str(url)).hostname} fully loaded, size: {len(data)}")


def decode_data(data):
    return NSString.alloc().initWithData_encoding_(data, NSUTF8StringEncoding)


def continue_runloop():
    NSRunLoop.mainRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.01))
