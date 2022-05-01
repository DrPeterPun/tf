from threading import Timer
from time import sleep
a = 0

def rt():
    global a
    print("timer +" + str(a))
    a = 0
    Timer(1, lambda: rt()).start()

rt()
while(True):
    a+=1
    #print("shile wsleep" + str(a))

