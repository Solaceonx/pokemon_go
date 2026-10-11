import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const context={};
vm.runInNewContext(fs.readFileSync(new URL('./viewer_values.js',import.meta.url),'utf8'),context);
const unknown={value:null,status:'unknown'};
const mon={species:{value:'Lanturn',status:'retained'},cp:{value:1493,status:'retained'},
  health:{value:[.48,.52],status:'retained',integer_hp_range:null,maximum_hp:null},
  energy:{value:[70,74],status:'pending',pending_event:{reason:'Attack may spend energy'}}};
const raw={species:unknown,cp:unknown,health_bar:unknown,health_estimate:{status:'unknown'},energy:{value:80,status:'inferred'}};
const frame={mine:raw,game_state:{sides:{mine:{active:'Lanturn:1493',active_status:'retained',
  pokemon:{'Lanturn:1493':mon},shields:{value:2,status:'retained'},left:{value:3,status:'retained'}}},
  pending_attack:{side:'mine'}}};
const displayed=context.battleStateValues(frame,'mine');
assert.equal(displayed.species.value,'Lanturn');
assert.equal(displayed.health_estimate.status,'retained');
assert.equal(JSON.stringify(displayed.health_estimate.fraction_range),'[0.48,0.52]');
assert.equal(displayed.health_bar.status,'unknown');
assert.equal(displayed.energy.status,'pending');
assert.equal(displayed.health_estimate.integer_hp_range,null);
assert.equal(raw.energy.status,'inferred');
assert.equal(raw.species.value,null);
const missing=structuredClone(frame);
missing.game_state.sides.mine.pokemon['Lanturn:1493'].health=unknown;
missing.game_state.sides.mine.pokemon['Lanturn:1493'].energy=unknown;
missing.game_state.sides.mine.shields=unknown;
const unavailable=context.battleStateValues(missing,'mine');
assert.equal(unavailable.health_estimate.status,'unknown');
assert.equal(unavailable.energy.status,'pending');
assert.equal(unavailable.shields_left.value,null);
assert.equal(Object.keys(context.battleStateValues(null,'mine')).length,0);
assert.equal(context.battleStateValues({mine:raw},'mine'),raw);
console.log(JSON.stringify({passed:true,checks:13,focus:'State carryover, pending model energy, unknown visible bars and immutable raw readings'}));
