const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
let published = 'eFvjoMcNbow', fail = false, tick, instance;
const frame = {src:'https://www.youtube.com/embed/eFvjoMcNbow?autoplay=1&mute=1&controls=0&gordalenlive=1'};
const context = {
 URL, Map, Promise, Number,
 location:{href:'https://www.gordalen.nu/',origin:'https://www.gordalen.nu'},
 document:{currentScript:{dataset:{statusUrl:'/index.php?gordalen_live_status=1'}},querySelectorAll:()=>[frame],addEventListener:()=>{}},
 fetch:async()=>{if(fail)throw Error('offline'); return {ok:true,json:async()=>({success:true,data:[{video_id:published}]})};},
 setInterval:fn=>{tick=fn;},
 window:{Joomla:{getOptions:()=>({statusUrl:'/index.php?option=com_ajax',pollSeconds:30,maxLagSeconds:30})},YT:{PlayerState:{PLAYING:1},Player:class {
  constructor(f,options) { instance=this; this.id='eFvjoMcNbow'; this.current=0; this.loads=[]; queueMicrotask(()=>options.events.onReady({target:this})); }
  getDuration(){return 86400;} getCurrentTime(){return this.current;}
  seekTo(t){this.current=t;} mute(){} playVideo(){}
  getVideoData(){return {video_id:this.id};}
  loadVideoById(id){this.id=id;this.loads.push(id);}
 }}}
};
(async()=>{
 vm.runInNewContext(fs.readFileSync(__dirname+'/../plugin/media/js/player.js','utf8'),context);
 await new Promise(setImmediate);
 assert.equal(instance.current,86397,'startup should seek to live edge');
 assert(new URL(frame.src).searchParams.get('enablejsapi')==='1');
 instance.current=100; await tick(); assert.equal(instance.current,86397,'drift should recover');
 published='NEWLIVE1234'; await tick(); assert.equal(instance.id,published,'new live ID should load');
 await tick(); assert.equal(instance.loads.length,1,'unchanged ID should not reload');
 fail=true; await tick(); assert.equal(instance.id,'NEWLIVE1234','failure should preserve playback');
 console.log('PASS: start at live edge, recover lag, switch broadcast, avoid unnecessary reloads, preserve playback on network failure.');
})().catch(e=>{console.error(e);process.exit(1);});
