'use strict';
const assert = require('node:assert/strict');
const {berechnePreis} = require('../site.js');
for (const [wohnungen, haeuser, erwartet] of [[1,1,89],[2,1,148],[4,1,266],[4,2,296],[2,2,178],[200,1,11830],[200,200,17800]]) {
  assert.equal(berechnePreis(wohnungen,haeuser).gesamt, erwartet);
}
for (const [wohnungen, haeuser] of [['',1],[0,1],[-1,1],[1.5,1],[201,1],[2,3],[2,0],['NaN',1],['Infinity',1],['1e2',1],[1,'']]) {
  assert.equal(berechnePreis(wohnungen,haeuser), null);
}
console.log('Preisrechner: 7 Preisfälle und 11 ungültige Eingaben geprüft.');
