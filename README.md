# PyThreader

PyThreader (pronounced as pie threader) is a library built on top of the standard Python **threading** library module. It adds certain useful classes, which are supposed to extend the collection of the primitives intorduced by the _threading module_ and at the same time, make using them simpler.

## Primitive

Primitive is a class, which represents most primitive synchronization object. It combines essential functionality of _threading_'s Lock, Condition and Semaphore object into a single class. The user is supposed to derive their own subclasses from the Primitive class to build their own classes, implementing the desired functionality.


### Primitive as a Semaphore
Primitive constructior takes one optional argument, which is its gate capacity, used by the "gated" method described below. Essentially, this parameter controls the semaphore capacity of the Primitive object.

### Primitive as a Lock
Any primitive object can work like a **reentrant** lock (threaidng RLock), i.e. it can be locked and releasded. A Primitive object is locked using using _with_ statement:

```python
from pythreader import Primitive

class MyLock(Primitive):
    ...
    
l = MyLock()

...

with l:
    # do something while the object is "locked"
```

Wile the Primitive object is locked, no other thread can lock the object and will have to block until the thread which has locked it releases the lock.

### Primitive as a Condition
Every Primitive object has methods await() and wakeup()

#### await(timeout = None, function=None, arguments=())
Wait until another thread calls wakeup() method of the same object of the timeout occurs.

When the timeout argument is present and not None, it should be a floating point number specifying a timeout for the operation in seconds (or fractions thereof).

This is a convenient alternative to the standard Condition.wait() method provided by the threading module. Caller of the await() method does not have to acquire the lock associated with the condition explicitly. That is done inside the await() method, which works like this:
1. lock the object (acquire the lock associated with the underlying condition)
1. call the wait() method of the condition (this will unlock the object and lock it again)
1. if a _function_ was specified, call it with provided parameters like this (while the object is locked!):
   ```python
   value = function(*arguments)
   ```
1. unlock the object
1. return the value returned by the user supplied function, or None otherwise

Note that if the _function_ is specified, it is called regardless whether the wait() exited by time-out or not.

#### wakeup(n=1, all=False, function=None, arguments=())
Calling object's wakeup method will:

1. lock the obejct
1. if a function is specified, call it with given arguments:
   ```python
   function(*arguments)
   ```
1. wake up one or many or all threads blocked by the await() call
1. unlock the object

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

Note that calling a synchronized method of an object is equivalent to using _with_ statement with the object:

```python

class A(Primitive):

    def work(self):
        #...
        
    @synchronized
    def work_synchronized(self):
        self.work()
        
a = A()

a.work_synchronized()           # this is iquivalent to
with a: a.work()                # ..................... this

```

The difference is that work_synchronized forces object locking.

#### gated
Decorator "gated" makes sure only certain number of threads can have this method or any other gated mentod invoked concurrently. Maximum concurrency is defined when the Primitive object is initialized by its constructor:

```python
from pythreader import Primitive, gated

class Gate(Primitive):

    def __init__(self, concurrency):
        Primitive.__init__(self, concurrency)
    
    @gated
    def phase1(self, args):
        # do something ...
        
    @gated
    def phase2(self, args):
        # do something else ...

G = g(5)
```
In this example, at any time, only 5 threads can be executing G.phase1 and G.phase2 at the same time, combined. I.e. there could be 5 threads inside phase1 and 0 inside phase2, or 3 inside phase1 and 2 inside phase2.

        

