package com.github.malikovpro.dt.bsl.syntaxhelp.export;

import java.util.regex.Pattern;

/**
 * Turns syntax-helper HTML fragments into readable text: tags and
 * <code>{ссылка:...}</code> markers are dropped, link labels are kept.
 */
public final class HtmlPlainText {
    private static final Pattern ANCHOR = Pattern.compile("(?is)<a[^>]*>(.*?)</a>");
    private static final Pattern BLOCK_BREAK = Pattern.compile("(?i)<(br|/p|/li|/div|/tr|/td|/h[1-6])\\s*/?>");
    private static final Pattern TAG = Pattern.compile("<[^>]+>");
    private static final Pattern HELP_LINK = Pattern.compile("\\{[\\p{L}]+:[^{}]*;\\s*([^{};]+)\\}");
    private static final Pattern SPACES = Pattern.compile("[ \\t\\x0B\\f\\r]+");
    private static final Pattern MANY_NEWLINES = Pattern.compile("\\n{3,}");

    private HtmlPlainText() {
    }

    public static String convert(String html) {
	if (html == null || html.isBlank()) {
	    return "";
	}
	var text = ANCHOR.matcher(html).replaceAll("$1");
	text = BLOCK_BREAK.matcher(text).replaceAll("\n");
	text = TAG.matcher(text).replaceAll(" ");
	text = HELP_LINK.matcher(text).replaceAll("$1");
	text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
		.replace("&quot;", "\"").replace("&#39;", "'").replace("&amp;", "&");
	text = SPACES.matcher(text).replaceAll(" ");
	text = MANY_NEWLINES.matcher(text).replaceAll("\n\n");
	return text.trim();
    }
}
