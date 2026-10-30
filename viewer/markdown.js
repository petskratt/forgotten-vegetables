/* Mattermost's CommonMark, with archive-specific rendering for mentions and links.
   Loaded as a classic script so a file:// page can use it. Node can require it too. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.MMMarkdown = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  let parser = null;
  let renderer = null;

  function install(commonmark, safeUrl) {
    const proto = commonmark.HtmlRenderer.prototype;
    if (proto.__archive) return;
    proto.__archive = true;
    proto.at_mention = function (node) {
      this.out("@" + (node.mentionName || ""));
    };
    proto.channel_link = function (node) {
      this.out("~" + (node.channelName || ""));
    };
    proto.emoji = function (node) {
      this.out(node.literal || (node.emojiName ? ":" + node.emojiName + ":" : ""));
    };
    proto.hashtag = function (node) {
      this.out("#" + (node.hashtag || ""));
    };
    const link = proto.link;
    proto.link = function (node, entering) {
      if (!safeUrl(node.destination || "")) return;
      link.call(this, node, entering);
    };
    const image = proto.image;
    proto.image = function (node, entering) {
      if (!safeUrl(node.destination || "")) return;
      image.call(this, node, entering);
    };
  }

  function render(commonmark, source, safeUrl) {
    if (!parser) {
      install(commonmark, safeUrl);
      parser = new commonmark.Parser();
      renderer = new commonmark.HtmlRenderer({ safe: true, softbreak: "<br />\n" });
    }
    return renderer.render(parser.parse(String(source || ""))).replace(/<a href=/g, '<a rel="noreferrer" href=');
  }

  return { render: render };
});
