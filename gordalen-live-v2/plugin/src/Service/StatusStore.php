<?php
namespace Gordalen\Plugin\System\Gordalenlive\Service;
defined('_JEXEC') or die;
final class StatusStore {
    public function __construct(private string $path, private string $channel) {}
    public function read(): array {
        $data=is_readable($this->path) ? json_decode(file_get_contents($this->path),true) : null;
        if (!is_array($data) || ($data['channel_id']??'')!==$this->channel) return ['video_id'=>null,'checked_at'=>null];
        return ['video_id'=>$this->validId($data['video_id']??null), 'checked_at'=>$data['checked_at']??null];
    }
    private function validId($id): ?string {
        return is_string($id) && preg_match('/^[A-Za-z0-9_-]{11}$/D',$id) ? $id : null;
    }
    public function write(array $data): array {
        if (($data['channel_id']??'')!==$this->channel) throw new \InvalidArgumentException('Wrong channel',400);
        $id=$data['video_id']??null;
        if ($id!==null && $this->validId($id)===null) throw new \InvalidArgumentException('Invalid video ID',400);
        $checked=$data['checked_at']??null;
        if (!is_string($checked) || strtotime($checked)===false) throw new \InvalidArgumentException('Invalid timestamp',400);
        $previous=$this->read();
        if ($previous['checked_at'] && strtotime($checked)<strtotime($previous['checked_at'])) throw new \InvalidArgumentException('Outdated status',409);
        $record=['channel_id'=>$this->channel,'video_id'=>$id,'checked_at'=>$checked];
        $dir=dirname($this->path);
        if (!is_dir($dir) && !mkdir($dir,0755,true) && !is_dir($dir)) throw new \RuntimeException('Cannot create status directory',500);
        $temp=tempnam($dir,'live-');
        if ($temp===false) throw new \RuntimeException('Cannot create status file',500);
        try {
            if(file_put_contents($temp,json_encode($record,JSON_THROW_ON_ERROR),LOCK_EX)===false) throw new \RuntimeException('Cannot write status',500);
            chmod($temp,0644);
            if(!rename($temp,$this->path)) throw new \RuntimeException('Cannot publish status',500);
        } finally { if(is_file($temp)) unlink($temp); }
        return ['video_id'=>$id,'checked_at'=>$checked];
    }
}
