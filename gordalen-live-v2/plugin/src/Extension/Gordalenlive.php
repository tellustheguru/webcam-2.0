<?php
namespace Gordalen\Plugin\System\Gordalenlive\Extension;
defined('_JEXEC') or die;
use Joomla\CMS\Event\Plugin\AjaxEvent;
use Joomla\CMS\Plugin\CMSPlugin;
use Joomla\CMS\Uri\Uri;
use Joomla\Event\SubscriberInterface;
use Gordalen\Plugin\System\Gordalenlive\Service\StatusStore;
final class Gordalenlive extends CMSPlugin implements SubscriberInterface {
    public static function getSubscribedEvents(): array {
        return ['onAfterInitialise'=>'loadYootheme','onBeforeCompileHead'=>'loadAssets','onAjaxGordalenlive'=>'ajax'];
    }
    private function store(): StatusStore {
        $path=trim((string)$this->params->get('status_file',''));
        if ($path==='') $path=JPATH_ROOT.'/media/plg_system_gordalenlive/status.json';
        return new StatusStore($path,(string)$this->params->get('channel_id',''));
    }
    public function loadYootheme($event): void {
        if (!class_exists(\YOOtheme\Application::class)) return;
        $application=\YOOtheme\Application::getInstance();
        $application->load(dirname(__DIR__,2).'/yootheme/bootstrap.php');
    }
    public function loadAssets($event): void {
        $app=$this->getApplication();
        if (!$app->isClient('site') || $app->getDocument()->getType()!=='html') return;
        $document=$app->getDocument();
        $document->addScriptOptions('gordalenLive',[
            'statusUrl'=>Uri::root(true).'/index.php?option=com_ajax&plugin=gordalenlive&group=system&format=json',
            'pollSeconds'=>max(15,min(300,(int)$this->params->get('poll_seconds',30))),
            'maxLagSeconds'=>max(10,min(120,(int)$this->params->get('max_lag_seconds',30))),
        ]);
        $document->getWebAssetManager()->registerAndUseScript('plg_system_gordalenlive.player','media/plg_system_gordalenlive/js/player.js',['version'=>'2.0.0'],['defer'=>true],['core']);
    }
    public function ajax(AjaxEvent $event): void {
        $app=$this->getApplication();
        $app->setHeader('Cache-Control','no-store, max-age=0',true);
        if ($app->getInput()->getMethod()==='POST') {
            $expected=(string)$this->params->get('publish_key','');
            $actual=(string)$app->getInput()->server->get('HTTP_X_GORDALEN_KEY','','raw');
            if(strlen($expected)<32 || !hash_equals($expected,$actual)) throw new \RuntimeException('Unauthorized publisher',403);
            $raw=file_get_contents('php://input',false,null,0,4097);
            if(strlen($raw)>4096) throw new \InvalidArgumentException('Payload too large',413);
            $data=json_decode($raw,true,16,JSON_THROW_ON_ERROR);
            if(!is_array($data)) throw new \InvalidArgumentException('Invalid status',400);
            $result=$this->store()->write($data);
        } else $result=$this->store()->read();
        $event->addResult($result);
    }
}
