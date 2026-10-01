obj-m := snd-hda-codec-ca0132.o
snd-hda-codec-ca0132-y := ca0132.o
ccflags-y := -I$(src)

KDIR ?= /lib/modules/$(shell uname -r)/build

default:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
