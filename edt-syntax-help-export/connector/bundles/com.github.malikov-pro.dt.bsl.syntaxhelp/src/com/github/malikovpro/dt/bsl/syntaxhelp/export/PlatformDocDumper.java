package com.github.malikovpro.dt.bsl.syntaxhelp.export;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

import org.eclipse.core.runtime.IProgressMonitor;
import org.eclipse.core.runtime.OperationCanceledException;

import com._1c.g5.v8.dt.platform.doc.PlatformDocEnvironment;
import com._1c.g5.v8.dt.platform.doc.PlatformDocPage;
import com._1c.g5.v8.dt.platform.doc.PlatformDocPageKind;
import com._1c.g5.v8.dt.platform.doc.PlatformDocProvider;
import com._1c.g5.v8.dt.platform.doc.PlatformDocTreeNode;
import com._1c.g5.v8.dt.platform.version.Version;
import com.github.malikovpro.dt.bsl.syntaxhelp.SyntaxHelpPlugin;

public final class PlatformDocDumper {
    private static final String[] BODY_SECTIONS = {
	    PlatformDocPage.TITLE,
	    PlatformDocPage.HEADING,
	    PlatformDocPage.DESCRIPTION,
	    PlatformDocPage.PARAMETER,
	    PlatformDocPage.RETURN,
	    PlatformDocPage.AVAILABILITY,
	    PlatformDocPage.AVAILABLE_SINCE,
	    PlatformDocPage.EXAMPLE,
	    PlatformDocPage.NOTE,
	    PlatformDocPage.REMARK,
	    PlatformDocPage.SEE_ALSO,
	    PlatformDocPage.DEPRECATE,
	    PlatformDocPage.DEFAULT,
	    PlatformDocPage.PROPERTY_USAGE,
	    PlatformDocPage.COLLECTION_ELEMENTS,
	    PlatformDocPage.USE_IN_THE_INTERFACE,
	    PlatformDocPage.INTERFACE,
	    PlatformDocPage.VALUE
    };
    private static final Pattern VERSION = Pattern.compile("(\\d+\\.\\d+(?:\\.\\d+)?)");

    private final PlatformDocProvider provider;
    private final Version version;
    private final String layer;

    public PlatformDocDumper(PlatformDocProvider provider, Version version, String layer) {
	this.provider = provider;
	this.version = version;
	this.layer = layer;
    }

    public List<DocCard> dump(IProgressMonitor monitor) throws Exception {
	var tree = provider.getTree(version);
	if (tree == null || tree.getRootNode() == null) {
	    throw new IllegalStateException("Пустое дерево справки для слоя " + layer);
	}
	var cards = new ArrayList<DocCard>();
	walk(tree.getRootNode(), null, cards, monitor);
	return cards;
    }

    private void walk(PlatformDocTreeNode node, Names type, List<DocCard> cards, IProgressMonitor monitor) {
	if (monitor != null && monitor.isCanceled()) {
	    throw new OperationCanceledException();
	}
	if (node == null) {
	    return;
	}
	var catalog = Boolean.TRUE.equals(node.getIsCatalog());
	var nextType = type;
	if (!catalog && isTypePage(node)) {
	    nextType = namesOf(node);
	}
	if (!catalog && node.isStored()) {
	    var card = cardOf(node, nextType);
	    if (card != null) {
		cards.add(card);
		if (monitor != null) {
		    monitor.subTask(layer + ": " + card.fullNameRu + " (" + cards.size() + ")");
		    monitor.worked(1);
		}
	    }
	}
	for (var child : children(node)) {
	    walk(child, nextType, cards, monitor);
	}
    }

    private DocCard cardOf(PlatformDocTreeNode node, Names type) {
	try {
	    var path = node.getPath();
	    if (path == null || path.isBlank()) {
		return null;
	    }
	    var page = provider.loadPage(path, version, "ru");
	    if (page == null) {
		return null;
	    }
	    var body = bodyOf(page);
	    if (body.isBlank()) {
		return null;
	    }
	    var self = namesOf(node);
	    var memberPage = type != null && !isTypePage(node);
	    var objectRu = memberPage ? type.ru : self.ru;
	    var objectEn = memberPage ? type.en : self.en;
	    var memberRu = memberPage ? self.ru : null;
	    var memberEn = memberPage ? self.en : null;
	    var fullRu = composeName(objectRu, memberRu);
	    if (fullRu.isBlank()) {
		fullRu = path;
	    }
	    var card = new DocCard(path, layer, kindOf(page.getKind()), fullRu, body);
	    card.objectRu = emptyToNull(objectRu);
	    card.objectEn = emptyToNull(objectEn);
	    card.memberRu = emptyToNull(memberRu);
	    card.memberEn = emptyToNull(memberEn);
	    card.fullNameEn = emptyToNull(composeName(objectEn, memberEn));
	    card.syntax = emptyToNull(HtmlPlainText.convert(page.getSyntax()));
	    if (card.syntax == null) {
		card.syntax = emptyToNull(syntaxVariants(page));
	    }
	    card.introducedIn = introducedIn(page);
	    card.availability = availabilityOf(page);
	    addAlias(card, objectRu);
	    addAlias(card, objectEn);
	    addAlias(card, memberRu);
	    addAlias(card, memberEn);
	    addAlias(card, fullRu);
	    addAlias(card, card.fullNameEn);
	    addAlias(card, node.getElementName(true));
	    addAlias(card, node.getElementName(false));
	    return card;
	} catch (Exception e) {
	    SyntaxHelpPlugin.logWarning("Пропуск страницы " + node.getPath() + ": " + e.getMessage());
	    return null;
	}
    }

    private static String bodyOf(PlatformDocPage page) {
	var parts = new ArrayList<String>();
	addPart(parts, HtmlPlainText.convert(page.getSyntax()));
	addPart(parts, syntaxVariants(page));
	for (var section : BODY_SECTIONS) {
	    addPart(parts, HtmlPlainText.convert(page.getValue(section)));
	}
	return String.join("\n\n", parts);
    }

    private static String syntaxVariants(PlatformDocPage page) {
	var parts = new ArrayList<String>();
	for (var i = 0; i < 8; i++) {
	    try {
		addPart(parts, HtmlPlainText.convert(page.getSyntaxVariantSyntax(i)));
	    } catch (RuntimeException e) {
		break;
	    }
	}
	return String.join("\n", parts);
    }

    private static String introducedIn(PlatformDocPage page) {
	var raw = HtmlPlainText.convert(page.getValue(PlatformDocPage.AVAILABLE_SINCE));
	if (raw.isBlank()) {
	    return null;
	}
	var matcher = VERSION.matcher(raw);
	return matcher.find() ? matcher.group(1) : raw;
    }

    private static String availabilityOf(PlatformDocPage page) {
	var environments = page.getEnvironments();
	if (environments != null && !environments.isEmpty()) {
	    var names = new ArrayList<String>();
	    for (PlatformDocEnvironment environment : environments) {
		if (environment != null) {
		    names.add(environment.name().toLowerCase(Locale.ROOT));
		}
	    }
	    if (!names.isEmpty()) {
		return String.join(",", names);
	    }
	}
	return emptyToNull(HtmlPlainText.convert(page.getValue(PlatformDocPage.AVAILABILITY)));
    }

    private static String kindOf(PlatformDocPageKind kind) {
	if (kind == null) {
	    return "type";
	}
	return switch (kind) {
	case PROPERTY -> "property";
	case PROCEDURE, FUNCTION -> "method";
	case EVENT -> "event";
	case CONSTRUCTOR -> "constructor";
	case TYPE -> "type";
	case OPERATOR -> "operator";
	case CONTROL_STATEMENT -> "statement";
	case DEFINITION -> "definition";
	case FORM_PARAMETER -> "form_parameter";
	case LITERAL -> "literal";
	case VALUE_SET -> "value_set";
	case VALUE_SET_VALUE -> "value";
	case ENUM -> "enum";
	case ENUM_VALUE -> "enum_value";
	case QUERY_TABLE -> "query_table";
	case QUERY_TABLE_FIELD -> "query_field";
	case QUERY_TABLE_PARAMETER -> "query_parameter";
	case CATALOG -> "catalog";
	};
    }

    private static boolean isTypePage(PlatformDocTreeNode node) {
	if (Boolean.TRUE.equals(node.getIsCatalog())) {
	    return false;
	}
	var path = node.getPath();
	if (path == null) {
	    return false;
	}
	var lower = path.toLowerCase(Locale.ROOT);
	return !lower.contains("/methods/") && !lower.contains("/properties/") && !lower.contains("/events/");
    }

    private static Names namesOf(PlatformDocTreeNode node) {
	return new Names(firstNonBlank(node.getName("ru"), node.getElementName(false)),
		firstNonBlank(node.getName("en"), node.getElementName(true)));
    }

    private static Collection<PlatformDocTreeNode> children(PlatformDocTreeNode node) {
	var children = node.getChildren();
	return children != null ? children : List.of();
    }

    private static String composeName(String object, String member) {
	if (object == null || object.isBlank()) {
	    return member == null ? "" : member.trim();
	}
	if (member == null || member.isBlank()) {
	    return object.trim();
	}
	return object.trim() + "." + member.trim();
    }

    private static void addAlias(DocCard card, String alias) {
	if (alias != null && !alias.isBlank()) {
	    card.aliases.add(alias.trim());
	}
    }

    private static void addPart(List<String> parts, String text) {
	if (text != null && !text.isBlank()) {
	    parts.add(text.trim());
	}
    }

    private static String firstNonBlank(String... values) {
	for (var value : values) {
	    if (value != null && !value.isBlank()) {
		return value.trim();
	    }
	}
	return "";
    }

    private static String emptyToNull(String value) {
	return value == null || value.isBlank() ? null : value;
    }

    private static final class Names {
	private final String ru;
	private final String en;

	private Names(String ru, String en) {
	    this.ru = ru;
	    this.en = en;
	}
    }
}
