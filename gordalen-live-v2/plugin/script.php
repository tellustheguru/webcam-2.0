<?php
defined('_JEXEC') or die;
use Joomla\CMS\Factory;
use Joomla\CMS\Table\Table;
use Joomla\Database\DatabaseInterface;
class PlgSystemGordalenliveInstallerScript {
    public function preflight($type,$parent): bool {
        if(version_compare(PHP_VERSION,'8.1','<')) throw new RuntimeException('PHP 8.1 or newer is required');
        return true;
    }
    public function postflight($type,$parent): void {
        if($type==='uninstall') return;
        // Clean only files from the superseded v1 plugin, never Joomla/YOOtheme.
        $legacy=JPATH_ROOT.'/plugins/system/gordalenlive/player.js';
        if(is_file($legacy)) unlink($legacy);
        // Migrate existing local status into the extension-owned storage once.
        $destination=JPATH_ROOT.'/media/plg_system_gordalenlive/status.json';
        if(!is_file($destination)) {
            $db=Factory::getContainer()->get(DatabaseInterface::class);
            $table=Table::getInstance('Extension');
            if($table->load(['type'=>'plugin','folder'=>'system','element'=>'gordalenlive'])) {
                $params=new Joomla\Registry\Registry($table->params);
                $source=(string)$params->get('status_file','');
                if($source && is_readable($source)) {
                    $data=json_decode(file_get_contents($source),true);
                    if(is_array($data) && preg_match('/^[A-Za-z0-9_-]{11}$/D',$data['video_id']??'')) {
                        $data['channel_id']=(string)$params->get('channel_id','');
                        file_put_contents($destination,json_encode($data,JSON_THROW_ON_ERROR)); chmod($destination,0644);
                    }
                }
                $params->set('status_file','');
                $table->params=$params->toString();
                if(!$table->store()) throw new RuntimeException('Failed to migrate plugin configuration');
            }
        }
        $namespace=JPATH_ADMINISTRATOR.'/cache/autoload_psr4.php';
        if(is_file($namespace)) unlink($namespace);
    }
    public function uninstall($parent): void {
        $status=JPATH_ROOT.'/media/plg_system_gordalenlive/status.json';
        if(is_file($status)) unlink($status);
        // Publisher is a separate server service; remove it separately as documented.
    }
}
