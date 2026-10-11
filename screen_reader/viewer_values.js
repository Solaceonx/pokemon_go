// Playback-driven values and independent review labels. No detector output is
// copied into review inputs; exports preserve nulls and observation statuses.
function createValueSheet({$,esc,time,getSource,video}) {
  const key='battle-lens-human-labels-v1';
  let reviews=[];
  try {reviews=JSON.parse(localStorage.getItem(key)||'[]');if(!Array.isArray(reviews))reviews=[]}catch{}
  const value=f=>f?.value??null;
  const percent=v=>Number.isFinite(v)?(100*v).toFixed(1)+'%':'Unknown';
  function flatten(frame,side,source){
    const v=frame[side]||{},e=v.health_estimate||{};
    return {battle_id:source.battle_id||source.id,clip_seconds:frame.t,
      source_seconds:frame.t+(source.source_start||0),side,phase:value(frame.phase),
      phase_estimate:value(frame.phase_estimate),phase_estimate_status:frame.phase_estimate?.status||'unknown',
      species:value(v.species),species_status:v.species?.status||'unknown',cp:value(v.cp),
      cp_status:v.cp?.status||'unknown',visible_health_status:v.health_bar?.status||'unknown',
      visible_health_fraction:value(v.health_bar)?.fraction??null,
      health_fraction_low:e.fraction_range?.[0]??null,health_fraction_high:e.fraction_range?.[1]??null,
      health_status:e.status||'unknown',integer_hp_low:e.integer_hp_range?.[0]??null,
      integer_hp_high:e.integer_hp_range?.[1]??null,maximum_hp:e.maximum_hp??null,
      shields_left:value(v.shields_left),pokemon_left:value(v.pokemon_left),
      shields_status:v.shields_left?.status||'unknown',pokemon_left_status:v.pokemon_left?.status||'unknown',
      energy:value(v.energy),energy_low:v.energy?.range?.[0]??null,energy_high:v.energy?.range?.[1]??null,
      energy_status:v.energy?.status||'unknown',fast_move:v.model?.fast_move?.name??null,
      fast_move_status:v.model?.fast_move?.known_from??'unknown',
      charged_moves:(v.model?.charged_moves||[]).map(m=>`${m.name} · ${m.known_from}`).join(', '),
      attack_stage:v.model?.attack_stage??null,defense_stage:v.model?.defense_stage??null,
      switch_ready_in:v.model?.switch_ready_in??null,tracking_consistency:source.tracking_verdict?.verdict??'not checked',
      reason:e.reason||e.meaning||'No health estimate'};
  }
  function row(r){
    const hp=r.integer_hp_low===null?'Unknown':`${r.integer_hp_low}–${r.integer_hp_high}/${r.maximum_hp}`;
    const scene=(r.phase??r.phase_estimate)?.replaceAll('_',' ')||'Unknown';
    const fields=[time(r.clip_seconds),r.side==='mine'?'Us':'Opponent',
      (r.species??'Unknown')+(r.species_status==='stale'?' · stale':''),(r.cp??'Unknown')+(r.cp_status==='stale'?' · stale':''),
      percent(r.visible_health_fraction),r.health_fraction_low===null?'Unknown':`${percent(r.health_fraction_low)}–${percent(r.health_fraction_high)}`,
      r.health_status,hp,r.shields_left??'Unknown',r.pokemon_left??'Unknown',
      (r.energy_low!==null?`${r.energy_low}–${r.energy_high}`:r.energy??'Unknown')+` · ${r.energy_status}`,
      r.fast_move?`${r.fast_move} · ${r.fast_move_status}`:'Unknown',r.charged_moves||'Unknown',
      r.attack_stage===null?'Unknown':`${r.attack_stage}/${r.defense_stage} · inferred`,
      r.switch_ready_in===null?'Unknown':`${r.switch_ready_in}s · inferred`,
      scene+(r.phase===null&&r.phase_estimate?` · ${r.phase_estimate_status}`:''),r.reason];
    return '<tr>'+fields.map(v=>`<td>${esc(v)}</td>`).join('')+'</tr>';
  }
  function render(t,frame){
    const source=getSource();
    $('values-current').innerHTML=frame?['mine','opponent'].map(s=>row(flatten(frame,s,source))).join(''):'<tr><td colspan="17">No recorded values at this time.</td></tr>';
    $('values-time').textContent=frame?`Recorded ${time(frame.t)} · follows playback`:'No coverage';
    const history=[];let last=-Infinity;
    for(const r of source.readings){if(r.t>t+0.000001)break;if(r.t-last>=.5-1e-6){history.push(r);last=r.t}}
    $('values-history').innerHTML=history.slice(-15).flatMap(r=>['mine','opponent'].map(s=>row(flatten(r,s,source)))).join('')||'<tr><td colspan="17">No earlier readings.</td></tr>';
    $('review-time').textContent=`Label video at ${time(t)} · ${reviews.filter(r=>r.battle_id===(source.battle_id||source.id)).length} saved labels for this battle`;
  }
  function download(rows,name){
    const url=URL.createObjectURL(new Blob([rows.map(r=>JSON.stringify(r)).join('\n')+'\n'],{type:'application/x-ndjson'}));
    const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  $('values-export').onclick=()=>{const source=getSource();download(source.readings.flatMap(r=>['mine','opponent'].map(s=>flatten(r,s,source))),`${source.battle_id||source.id}-values.jsonl`)};
  for(const [name,label] of Object.entries({normal_fighting:'Normal fighting',shield_prompt:'Shield choice',opponent_charged_warning:'Incoming charge warning',my_charged_minigame:'Our charge minigame',charged_resolution:'Charge resolves',choose_next:'Our replacement choice',opponent_replacement_wait:'Waiting for opponent replacement',switching_in:'Pokémon enters',countdown:'Countdown',result:'Result',unknown:'Uncertain'})){
    const option=document.createElement('option');option.value=name;option.textContent=label;$('review-phase').append(option);
  }
  $('review-blind').onchange=()=>{video.pause();document.body.classList.toggle('blind-review',$('review-blind').checked)};
  $('review-form').addEventListener('focusin',()=>video.pause());
  $('review-form').onsubmit=event=>{
    event.preventDefault();video.pause();
    const source=getSource(),label={battle_id:source.battle_id||source.id,clip_seconds:Number(video.currentTime.toFixed(6)),provenance:'human_review',reviewed_without_predictions:$('review-blind').checked};
    const phase=$('review-phase').value;if(phase)label.phase=phase;
    try {
      for(const side of ['mine','opponent']){
        const fields={},species=$(`review-${side}-species`).value.trim();if(species)fields.species=species;
        const low=$(`review-${side}-low`).value,high=$(`review-${side}-high`).value;
        if(low!==''||high!==''){
          if(low===''||high==='')throw Error('Enter both health range endpoints, or leave both blank.');
          const a=Number(low),b=Number(high);if(!Number.isFinite(a)||!Number.isFinite(b)||a<0||b>100||a>b)throw Error('Health range must be ordered and between 0% and 100%.');
          fields.health_fraction_range=[a/100,b/100];
        }
        if(Object.keys(fields).length)label[side]=fields;
      }
      if(!label.phase&&!label.mine&&!label.opponent)throw Error('Enter at least one label you can identify from the video.');
      const index=reviews.findIndex(r=>r.battle_id===label.battle_id&&Math.abs(r.clip_seconds-label.clip_seconds)<.000001);
      const next=reviews.slice();if(index>=0)next[index]=label;else next.push(label);
      localStorage.setItem(key,JSON.stringify(next));reviews=next;
      $('review-message').textContent='Saved locally. Export labels to include them in repeatable evaluation.';
      $('review-form').reset();$('review-blind').checked=document.body.classList.contains('blind-review');
      $('review-time').textContent=`Label video at ${time(video.currentTime)} · ${reviews.filter(r=>r.battle_id===label.battle_id).length} saved labels for this battle`;
    }catch(error){$('review-message').textContent=error.message}
  };
  $('review-export').onclick=()=>download(reviews,'human-review-labels.jsonl');
  return {render,flatten,getReviews:()=>reviews.slice()};
}
