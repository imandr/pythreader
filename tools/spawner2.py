import subprocess, time, sys, getopt, os
from threads import TaskQueue, Subprocess, Task

class SubprocessTask(Task):

    def __init__(self, index, ntotal, command_template):
        Task.__init__(self)
        self.CommandTemplate = command_template
        self.NTotal = ntotal
        self.Index = index
        
    def run(self):
        command = [c.replace("[i]", "%d" % (self.Index,)) for c in self.CommandTemplate]
        env = {}
        env.update(os.environ)
        env.update(
            {
                "SPAWNER_PROCESS_NUMBER":"%d" % (self.Index,),
                "SPAWNER_TOTAL_PROCESSES":"%s" % (self.NTotal,)
            }
        )
        print "\nStaring %d: %s" % (self.Index, " ".join(command))
        sp = Subprocess(command, env=env)
        sp.wait()
        print "\n%d is done" % (self.Index,)
        
Usage = """python spawner.py [options] command [args...]
    Options:   -m <max concurrency>
               -n <number of tasks>
               -s <stagger interval in seconds>
               -N <n> - run all <n> tasks at once
            """

MaxPipes = 30
NRUN = 1000
stagger = 0.1

output = None  #open("/dev/null", "w")

opts, args = getopt.getopt(sys.argv[1:], "m:n:s:N:")
for opt, val in opts:
    if opt == '-m': MaxPipes = int(val)
    if opt == '-n': NRUN = int(val)
    if opt == '-s': stagger = float(val)
    if opt == '-N': 
        NRUN = int(val)
        MaxPipes = NRUN

if not args:
    print Usage
    sys.exit(1)

command = args

tq = TaskQueue(MaxPipes)
for i in xrange(NRUN):
    tq.addTask(SubprocessTask(i, NRUN, command))
    time.sleep(stagger)
    
tq.waitUntilEmpty()





