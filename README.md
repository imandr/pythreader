# PyThreader

PyThreader (pronounced as pie threader) is a library built on top of the standard Python **threading** library module. It adds certain useful classes, which are supposed to extend the collection of the primitives intorduced by the _threading module_ and at the same time, make using them simpler.

## Primitive

Primitive is a class, which represents most primitive synchronization object. It combines essential functionality of _threading_'s Lock, Condition and Semaphore object into a single class. The user is supposed to derive their own subclasses from the Primitive class to build their own classes, implementing the desired functionality.

### Decorators
PyThreader provides 2 decorator functions, named "sychronized" and "gated", which can be attributed to methods of Primitive subclasses.

#### synchronized
Decorator "synchronized" is very similar to "synchronized" method attribute in Java. If the Primitive subclass metod is decorated as "synchronized", it becomes a critical section in the sense that once a thread A's execution enters the decorated method "p", any other thread (B) calling this or any other "synchronized" method "q" of the same object (not class) will block before entering the method "q" until thread A exits mething "p".

For example:

```python
from pythreader import Primitive, synchronized

class Buffer(Primitive):

    def __init__(self):
        Primitive.__init__(self)
        self.Buf = []
        
    @synchronized
    def push(self, x):
        self.Buf.append(x)
        self.Buf.sort()
        
    @synchronized
    def pop(self):
        item = None
        if self.Buf:
            item = x[0]
            self.Buf = self.Buf[1:]
        return item
```