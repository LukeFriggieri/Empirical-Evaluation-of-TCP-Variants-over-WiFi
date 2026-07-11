obj-m += tcp_veno_adaptiveBeta.o
obj-m += tcp_veno_rttguard.o

all:
	make -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules

clean:
	make -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean