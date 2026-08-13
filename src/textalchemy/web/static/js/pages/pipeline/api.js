"use strict";

function form(spec) {
    return new URLSearchParams({spec});
}

export const pipelineApi = {
    operations: () => window.api('/api/operations'),
    toYaml: (spec) => window.api('/api/pipeline/yaml', {method: 'POST', body: form(spec)}),
    parse: (spec) => window.api('/api/pipeline/parse', {method: 'POST', body: form(spec)}),
    validate: (spec) => window.api('/api/pipeline/validate', {method: 'POST', body: form(spec)}),
    run: (spec) => window.api('/api/pipeline/run', {method: 'POST', body: form(spec)}),
};
