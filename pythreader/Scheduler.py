from .core import PyThread, synchronized
from .task_queue import Task, TaskQueue
import time, uuid, traceback, random
import sys

class Job(object):
    
    def __init__(self, id, t, interval, jitter, fcn, params, args):
        self.F = fcn
        self.Params = params or ()
        self.Args = args or {}
        self.ID = id
        self.Interval = interval
        self.Jitter = jitter or 0.0
        self.NextT = t
        
    def __str__(self):
        return f"Job({self.ID})"
        
    __repr__ = __str__
        
    def execute(self):
        start = time.time()
        try:
            next_t = self.F(*self.Params, **self.Args)
        except:
            print(f"Error in job {self.Job.ID}:", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            next_t = None
        if next_t is None:
            if self.Interval is not None:
                next_t = start + self.Interval + random.random() * self.Jitter
        elif next_t == "stop":
            next_t = None
        elif next_t < 3.0e7:
            # if next_t is < 1980, it's relative time
            next_t += start + random.random() * self.Jitter
        return next_t

class JobTask(Task):
    
    def __init__(self, scheduler, job):
        Task.__init__(self, name=f"JobTask({job.ID})")
        self.Scheduler = scheduler
        self.Job = job

    def __str__(self):
        return f"JobTask({self.Job.ID})"

    __repr__ = __str__

    def run(self):
        job = self.Job
        scheduler = self.Scheduler
        self.Job = self.Scheduler = None         # break circual links
        next_t = job.execute()
        if next_t is not None:
            scheduler.add_job(job, next_t)

class Scheduler(PyThread):
    def __init__(self, max_concurrent = 10, stop_when_empty = False):
        PyThread.__init__(self)
        self.Timeline = []      # [job, ...]
        self.Queue = TaskQueue(max_concurrent, delegate=self)
        self.StopWhenEmpty = stop_when_empty
        self.Stop = False
        
    # delegate interface used to wait until the task queue is empty
    def taskEnded(self, *params):
        self.wakeup()
        
    def taskFailed(self, *params):
        self.wakeup()
        
    def stop(self):
        self.Stop = True
        self.wakeup()
        
    @synchronized
    def add_job(self, job, t):
        job.NextT = t
        self.Timeline = sorted(self.Timeline + [job], key=lambda j: j.NextT)
        self.wakeup()
        
    @synchronized        
    def add(self, fcn, *params, interval=None, t0=None, id=None, jitter=0.0, param=None, **args):
        #
        # t0 - first time to run the task. Default:
        #   now + interval or now if interval is None
        # interval - interval to repeat the task. Default: do not repeat
        #
        # fcn:
        #   next_t = fcn()
        #   next_t = fcn(param)
        #   next_t = fcn(**args)
        # 
        #   next_t:
        #       "stop" - remove task
        #       int or float - next time to run
        #       None - run at now+interval next time
        #
        if param is not None:       # for backward compatibility
            params = (param,)
        if id is None:
            id = uuid.uuid4().hex
        if t0 is None:
            t0 = time.time() + (interval or 0.0) + random.random()*jitter
        job = Job(id, t0, interval, jitter, fcn, params, args)
        self.add_job(job, t0)
        return id
        
    @synchronized
    def remove(self, job_id):
        self.Timeline = [j for j in self.Timeline if j.ID != job_id]
        
    @synchronized        
    def tick(self):
        while self.Timeline:
            job = self.Timeline[0]
            if job.NextT <= time.time():
                self.Timeline.pop(0)
                self.Queue.addTask(JobTask(self, job))
            else:
                break
                
    @synchronized        
    def is_empty(self):
        return not self.Timeline and self.Queue.is_empty()
                        
    def run(self):
        while not self.Stop and not (self.is_empty() and self.StopWhenEmpty):
            if self.Timeline:
                with self:
                    tmin = self.Timeline[0].NextT
                    now = time.time()
                    delta = tmin - time.time()
                    self.sleep(delta)
            elif not (self.Queue.is_empty() and self.StopWhenEmpty):
                self.sleep(10)
            self.tick()
            
    @synchronized        
    def wait_until_empty(self):
        while not self.is_empty():
            self.sleep(10)
    

if __name__ == "__main__":
    from datetime import datetime
    
    s = Scheduler()
    
    class NTimes(object):

        def __init__(self, n):
            self.LastRun = None
            self.N = n

        def __call__(self, message):
            t = datetime.now()
            delta = None if self.LastRun is None else t - self.LastRun
            print("%s: %s delta:%s" % (t.strftime("%H:%M:%S.%f"), message, delta))
            self.LastRun = t
            self.N -= 1
            time.sleep(0.2)
            if self.N <= 0:
                print("stopping", message)
                return "stop"

    #time.sleep(1.0)
    s.add(NTimes(10), "green 1.5 sec", interval=1.5)
    s.add(NTimes(7), "blue 0.5 sec", interval=0.5)
    s.start()

    print("waiting for the scheduler to finish...")
    #s.join()
    s.wait_until_empty()
    s.stop()
    s.join()
    print("stopped")
