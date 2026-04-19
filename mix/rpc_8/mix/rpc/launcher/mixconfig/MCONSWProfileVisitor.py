# Generated from external/mixrpc/launcher/mixconfig/MCONSWProfile.g4 by ANTLR 4.9.2
from antlr4 import *
if __name__ is not None and "." in __name__:
    from .MCONSWProfileParser import MCONSWProfileParser
else:
    from MCONSWProfileParser import MCONSWProfileParser

# This class defines a complete generic visitor for a parse tree produced by MCONSWProfileParser.

class MCONSWProfileVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by MCONSWProfileParser#sw_profile.
    def visitSw_profile(self, ctx:MCONSWProfileParser.Sw_profileContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#version.
    def visitVersion(self, ctx:MCONSWProfileParser.VersionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#module_search_paths.
    def visitModule_search_paths(self, ctx:MCONSWProfileParser.Module_search_pathsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#namespaces.
    def visitNamespaces(self, ctx:MCONSWProfileParser.NamespacesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#man_server.
    def visitMan_server(self, ctx:MCONSWProfileParser.Man_serverContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#app_server.
    def visitApp_server(self, ctx:MCONSWProfileParser.App_serverContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#url.
    def visitUrl(self, ctx:MCONSWProfileParser.UrlContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#config.
    def visitConfig(self, ctx:MCONSWProfileParser.ConfigContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#xavier.
    def visitXavier(self, ctx:MCONSWProfileParser.XavierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#default_ip.
    def visitDefault_ip(self, ctx:MCONSWProfileParser.Default_ipContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#base_ip.
    def visitBase_ip(self, ctx:MCONSWProfileParser.Base_ipContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#file_system.
    def visitFile_system(self, ctx:MCONSWProfileParser.File_systemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#allow_list.
    def visitAllow_list(self, ctx:MCONSWProfileParser.Allow_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#boolean.
    def visitBoolean(self, ctx:MCONSWProfileParser.BooleanContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#AnObject.
    def visitAnObject(self, ctx:MCONSWProfileParser.AnObjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#EmptyObject.
    def visitEmptyObject(self, ctx:MCONSWProfileParser.EmptyObjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#ArrayOfValues.
    def visitArrayOfValues(self, ctx:MCONSWProfileParser.ArrayOfValuesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#EmptyArray.
    def visitEmptyArray(self, ctx:MCONSWProfileParser.EmptyArrayContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#pair.
    def visitPair(self, ctx:MCONSWProfileParser.PairContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#String.
    def visitString(self, ctx:MCONSWProfileParser.StringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#Atom.
    def visitAtom(self, ctx:MCONSWProfileParser.AtomContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#ObjectValue.
    def visitObjectValue(self, ctx:MCONSWProfileParser.ObjectValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONSWProfileParser#ArrayValue.
    def visitArrayValue(self, ctx:MCONSWProfileParser.ArrayValueContext):
        return self.visitChildren(ctx)



del MCONSWProfileParser