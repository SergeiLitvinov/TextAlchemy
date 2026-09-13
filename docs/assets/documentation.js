// Replay an early query once MkDocs has finished building its search index.
window.addEventListener("DOMContentLoaded", function () {
    if (typeof searchWorker !== "undefined") {
        searchWorker.addEventListener("message", function (event) {
            const input = document.getElementById("mkdocs-search-query");
            if (event.data.allowSearch && input && input.value.trim()) {
                doSearch();
            }
        });
    }
});
