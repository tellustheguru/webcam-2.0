<?php
define('_JEXEC',1);
$root=sys_get_temp_dir().'/gordalen-uninstall-'.bin2hex(random_bytes(5));
define('JPATH_ROOT',$root); mkdir($root.'/media/plg_system_gordalenlive',0755,true);
file_put_contents($root.'/media/plg_system_gordalenlive/status.json','{}');
file_put_contents($root.'/keep.txt','unrelated');
require __DIR__.'/../plugin/script.php';
(new PlgSystemGordalenliveInstallerScript)->uninstall(null);
if(is_file($root.'/media/plg_system_gordalenlive/status.json') || !is_file($root.'/keep.txt')) throw new RuntimeException('Uninstall cleanup crossed ownership boundary');
unlink($root.'/keep.txt'); rmdir($root.'/media/plg_system_gordalenlive'); rmdir($root.'/media'); rmdir($root);
echo "PASS: uninstall removes managed status only; unrelated files remain.\n";
