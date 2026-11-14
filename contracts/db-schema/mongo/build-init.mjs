// Regenerates init.js from catalog.json:  node build-init.mjs
import { readFileSync, writeFileSync } from 'node:fs';
const here = new URL('.', import.meta.url);
const spec = JSON.parse(readFileSync(new URL('catalog.json', here), 'utf8'));
const js = `// GENERATED from catalog.json by build-init.mjs. Do not edit; edit catalog.json and rebuild.
// Run with:  mongosh "mongodb://localhost:27017" --file init.js
// Idempotent: creates missing collections, updates validators of existing ones, creates missing indexes.
const spec = ${JSON.stringify(spec, null, 2)};

const target = db.getSiblingDB(spec.database);
const existing = new Set(target.getCollectionNames());

for (const [name, def] of Object.entries(spec.collections)) {
  const options = { validator: def.validator, validationLevel: 'strict', validationAction: 'error' };
  if (existing.has(name)) {
    target.runCommand({ collMod: name, ...options });
    print('updated validator: ' + name);
  } else {
    target.createCollection(name, options);
    print('created collection: ' + name);
  }
  target.runCommand({ createIndexes: name, indexes: def.indexes });
  print('indexes ensured: ' + name + ' (' + def.indexes.length + ')');
}
`;
writeFileSync(new URL('init.js', here), js);
console.log('wrote init.js');
