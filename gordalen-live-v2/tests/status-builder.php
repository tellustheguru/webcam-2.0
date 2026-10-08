<?php
namespace Joomla\Registry { class Registry { private array $data; public function __construct($data){$this->data=is_array($data)?$data:json_decode($data,true);} public function get($name,$fallback=null){return $this->data[$name]??$fallback;} } }
namespace Joomla\CMS\Plugin { class PluginHelper { public static function getPlugin($group,$element){return (object)['params'=>$GLOBALS['params']];} } }
namespace Joomla\CMS\Uri { class Uri { public static function root(){return 'https://www.gordalen.nu/';} } }
namespace {
define('_JEXEC',1); define('JPATH_ROOT',sys_get_temp_dir());
require __DIR__.'/../plugin/src/Service/StatusStore.php';
require __DIR__.'/../plugin/src/Yootheme/BuilderIntegration.php';
function check($condition,$message){if(!$condition)throw new RuntimeException($message);}
$path=tempnam(sys_get_temp_dir(),'gordalen-test-'); unlink($path);
$store=new \Gordalen\Plugin\System\Gordalenlive\Service\StatusStore($path,'channel');
try {
 check($store->read()['video_id']===null,'missing status should be unknown');
 $store->write(['channel_id'=>'channel','video_id'=>'eFvjoMcNbow','checked_at'=>'2026-10-07T10:00:00Z']);
 foreach([
 ['channel_id'=>'wrong','video_id'=>'eFvjoMcNbow','checked_at'=>'2026-10-07T11:00:00Z'],
 ['channel_id'=>'channel','video_id'=>'invalid/path','checked_at'=>'2026-10-07T11:00:00Z'],
 ['channel_id'=>'channel','video_id'=>'eFvjoMcNbow','checked_at'=>'2026-10-07T09:00:00Z']
 ] as $bad) { $rejected=false; try{$store->write($bad);}catch(InvalidArgumentException $e){$rejected=true;} check($rejected,'invalid/replayed status accepted'); }
 check($store->read()['video_id']==='eFvjoMcNbow','failed writes must preserve previous ID');
 $GLOBALS['params']=['channel_id'=>'channel','status_file'=>$path];
 $builder=new class { public $callback; public function addTransform($phase,$callback){check($phase==='prerender','wrong API phase');$this->callback=$callback;} };
 \Gordalen\Plugin\System\Gordalenlive\Yootheme\BuilderIntegration::register($builder);
 $props=['video'=>'https://www.youtube.com/embed/live_stream?channel=channel','video_width'=>'960','video_height'=>'540','text_align'=>'center'];
 $node=(object)['type'=>'video','props'=>$props]; ($builder->callback)($node);
 check(str_contains($node->props['video'],'/embed/eFvjoMcNbow?'),'native source not resolved');
 foreach(['video_width','video_height','text_align'] as $key)check($node->props[$key]===$props[$key],'layout changed');
 $store->write(['channel_id'=>'channel','video_id'=>'NEWLIVE1234','checked_at'=>'2026-10-07T11:00:00Z']);
 $node=(object)['type'=>'video','props'=>$props]; ($builder->callback)($node); check(str_contains($node->props['video'],'/embed/NEWLIVE1234?'),'replacement ID not resolved');
 $other=(object)['type'=>'video','props'=>['video'=>'https://www.youtube.com/embed/live_stream?channel=other']]; $before=$other->props; ($builder->callback)($other); check($other->props===$before,'unrelated video modified');
 echo "PASS: status validation, stale-write rejection, new live ID, native 960x540 layout, unrelated videos preserved.\n";
} finally {if(is_file($path))unlink($path);}
}
