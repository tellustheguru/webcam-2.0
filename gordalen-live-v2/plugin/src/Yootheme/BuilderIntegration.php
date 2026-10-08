<?php
namespace Gordalen\Plugin\System\Gordalenlive\Yootheme;
defined('_JEXEC') or die;
use Joomla\CMS\Plugin\PluginHelper;
use Joomla\CMS\Uri\Uri;
use Joomla\Registry\Registry;
use Gordalen\Plugin\System\Gordalenlive\Service\StatusStore;
final class BuilderIntegration {
    public static function register($builder): void {
        $plugin=PluginHelper::getPlugin('system','gordalenlive');
        $params=new Registry($plugin->params??'{}');
        $channel=(string)$params->get('channel_id','');
        $path=trim((string)$params->get('status_file',''));
        if(!$path) $path=JPATH_ROOT.'/media/plg_system_gordalenlive/status.json';
        $store=new StatusStore($path,$channel);
        $builder->addTransform('prerender',function($node) use ($channel,$store) {
            if (($node->type??'')!=='video' || !$channel) return;
            $url=(string)($node->props['video']??''); $parts=parse_url($url); parse_str($parts['query']??'',$query);
            if (!in_array(strtolower($parts['host']??''),['www.youtube.com','www.youtube-nocookie.com'],true)
                || ($parts['path']??'')!=='/embed/live_stream' || ($query['channel']??'')!==$channel) return;
            $status=$store->read();
            $node->props['video']=$status['video_id'] ? 'https://www.youtube.com/embed/'.$status['video_id'].'?autoplay=1&mute=1&controls=0&playsinline=1&rel=0&enablejsapi=1&gordalenlive=1&origin='.rawurlencode(Uri::root()) : $url.'&gordalenlive=1';
        });
    }
}
