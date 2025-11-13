#!/usr/bin/env node

import fs from 'fs';

try {
    const data = fs.readFileSync('documentation-references.json', 'utf8');
    const refs = JSON.parse(data);

    console.log('✅ JSON is valid');
    console.log('Top level keys:', Object.keys(refs));

    if (refs.documentation_references) {
        console.log('Documentation references keys:', Object.keys(refs.documentation_references));

        if (refs.documentation_references.standards_and_policies) {
            console.log('Standards keys:', Object.keys(refs.documentation_references.standards_and_policies));

            if (refs.documentation_references.standards_and_policies.environmental_equivalence) {
                console.log('✅ Environmental Equivalence section found');
                console.log('EE2 content:', refs.documentation_references.standards_and_policies.environmental_equivalence);
            } else {
                console.log('❌ Environmental Equivalence section not found');
            }
        } else {
            console.log('❌ standards_and_policies section not found');
        }
    } else {
        console.log('❌ documentation_references section not found');
    }
} catch (error) {
    console.log('❌ JSON parsing error:', error.message);
}
