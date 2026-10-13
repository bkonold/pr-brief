export const DEFAULTS = {
  // Empty: no run server, and the brief is read from the pull request's comment.
  baseUrl: "",
};
export const TOKEN_KEY = "serverToken";
// Who owns the file pane on every PR page: "brief" or "host" (the host's own tree). Kept in chrome.storage.local.
export const PANE_OWNER_KEY = "paneOwner";
// The width in pixels Forgejo's file pane was dragged to. Kept in chrome.storage.local.
export const PANE_WIDTH_KEY = "forgejoPaneWidth";
