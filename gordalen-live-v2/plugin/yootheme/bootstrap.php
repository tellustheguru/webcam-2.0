<?php
defined('_JEXEC') or die;
use Gordalen\Plugin\System\Gordalenlive\Yootheme\BuilderIntegration;
return [
    'extend'=>[\YOOtheme\Builder::class=>[BuilderIntegration::class,'register']],
];
