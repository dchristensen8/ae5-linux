#include <linux/module.h>
#include <linux/export-internal.h>
#include <linux/compiler.h>

MODULE_INFO(name, KBUILD_MODNAME);

__visible struct module __this_module
__section(".gnu.linkonce.this_module") = {
	.name = KBUILD_MODNAME,
	.init = init_module,
#ifdef CONFIG_MODULE_UNLOAD
	.exit = cleanup_module,
#endif
	.arch = MODULE_ARCH_INIT,
};


MODULE_INFO(depends, "snd-hda-core,snd-hda-codec-generic,snd-hda-codec,snd,snd-pcm");

MODULE_ALIAS("hdaudio:v11020011r*a01*");

MODULE_INFO(srcversion, "A3EBB1D418A626B675324A3");
