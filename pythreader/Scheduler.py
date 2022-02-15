from .core import PyThread, synchronized
from .task_queue import Task, TaskQueue
import time, uuid, traceback, random
import sys

class Job(object):
    
    def __init__(self, id, interval, jitter, fcn, params, args):
        self.F = fcn
        self.Params = params or ()
        self.Args = args or {}
        self.ID = id
        self.Interval = interval
        self.Jitter = jitter or 0.0
        
    def __str__(self):
        return f"Job({self.ID})"
        
    __repr__ = __str__
        
    def execute(self, scheduler):
        start = time.time()
        next_t = self.F(*self.Params, **self.Args)
        if next_t is None:
            if self.Interval is not None:
                next_t = start + self.Interval + random.random() * self.Jitter
        elif next_t == "stop":
            next_t = None
        elif next_t < 3.0e7:
            # if next_t is < 1980, it's relative time
            next_t += start
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
        scheduler = self.Scheduler
        try:
            try:
                next_t = self.Job.execute(self.Scheduler)
            except:
                print(f"Error in job {self.Job.ID}:", file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
                next_t = None
            #print(self, "next_t:", next_t)
            if next_t is not None:
                scheduler.resubmit(self.Job, next_t)
            else:
                scheduler.remove(self.Job)
        finally:
            self.Scheduler = None               # make sure to break circular references
            self.Job = None

class Scheduler(PyThread):
    def __init__(self, max_concurrent = 100):
        PyThread.__init__(self)
        self.Timeline = []      # [(t, job), ...]
        self.Jobs = {}     # id -> (function, t, interval, params, args)
        self.Queue = TaskQueue(max_concurrent)
        
    @synchronized
    def add_to_timeline(self, job, t):
        self.Timeline = sorted([(t, j) for t, j in self.Timeline if j.ID != job.ID] + [(t, job)])
        
    @synchronized
    def remove_from_timeline(self, job):
        job_id = job.ID if isinstance(job, Job) else job
        self.Timeline = [(t, j) for t, j in self.Timeline if j.ID != job_id]
        
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
        job = Job(id, interval, jitter, fcn, params, args)
        self.Jobs[id] = job
        self.add_to_timeline(job, t0)
        self.wakeup()
        return id
        
    @synchronized
    def remove(self, job):
        job_id = job.ID if isinstance(job, Job) else job
        self.Jobs.pop(job_id, None)
        #print("    timeline before:", *((j.ID, j.ID != job_id) for t, j in self.Timeline))
        self.Timeline = [(t, j) for t, j in self.Timeline if j.ID != job_id]
        #print("    timeline after :", *((j.ID, j.ID != job_id) for t, j in self.Timeline))
        
    @synchronized
    def resubmit(self, job, t):
        #print("resubmit before:", self.Timeline)
        if job.ID in self.Jobs:
            # make sure the job was not removed
            self.add_to_timeline(job, t)
            self.wakeup()
        else:
            #print("resubmit: job", job.ID, "not found")
            pass
        #print("resubmit after:", self.Timeline)
        
    @synchronized        
    def tick(self):
        while self.Timeline:
            t, job = self.Timeline[0]
            if t <= time.time():
                self.Timeline.pop(0)
                self.Queue.addTask(JobTask(self, job))
            else:
                break
                        
    def run(self):
        while True:
            delta = 10.0
            with self:
                if self.Timeline:
                    tmin = self.Timeline[0][0]
                    now = time.time()
                    delta = tmin - time.time()
                if delta > 0.0:
                    self.sleep(delta)
            self.tick()

if __name__ == "__main__":
    from datetime import datetime
    
    s = Scheduler()
    
    class NTimes(object):
        
        def __init__(self, n):
            self.N = n
            
        def __call__(self, message):
            t = datetime.now()
            print("%s: %s" % (strftime(t, "%H:%M:%S.f"), message))
            self.N -= 1
            if self.N <= 0:
                print("stopping", message)
                return "stop"
                
    s.start()
    time.sleep(1.0)
    s.add(NTimes(10), 1.5, "green 1.5 sec")
    s.add(NTimes(7), 0.5, "blue 0.5 sec")

    s.join()

        
