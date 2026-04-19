# Generated from external/mixrpc/launcher/mixconfig/MCONHWProfile.g4 by ANTLR 4.9.2
from antlr4 import *
if __name__ is not None and "." in __name__:
    from .MCONHWProfileParser import MCONHWProfileParser
else:
    from MCONHWProfileParser import MCONHWProfileParser

# This class defines a complete generic visitor for a parse tree produced by MCONHWProfileParser.

class MCONHWProfileVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by MCONHWProfileParser#hw_profile.
    def visitHw_profile(self, ctx:MCONHWProfileParser.Hw_profileContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#version.
    def visitVersion(self, ctx:MCONHWProfileParser.VersionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#xavier_hw.
    def visitXavier_hw(self, ctx:MCONHWProfileParser.Xavier_hwContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#ip_pins.
    def visitIp_pins(self, ctx:MCONHWProfileParser.Ip_pinsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#ip_i2c_dev.
    def visitIp_i2c_dev(self, ctx:MCONHWProfileParser.Ip_i2c_devContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#expander.
    def visitExpander(self, ctx:MCONHWProfileParser.ExpanderContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#pins.
    def visitPins(self, ctx:MCONHWProfileParser.PinsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#app_server_services.
    def visitApp_server_services(self, ctx:MCONHWProfileParser.App_server_servicesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#service.
    def visitService(self, ctx:MCONHWProfileParser.ServiceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#plain_obj.
    def visitPlain_obj(self, ctx:MCONHWProfileParser.Plain_objContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#kw_arg.
    def visitKw_arg(self, ctx:MCONHWProfileParser.Kw_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#ctor.
    def visitCtor(self, ctx:MCONHWProfileParser.CtorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#ici_obj.
    def visitIci_obj(self, ctx:MCONHWProfileParser.Ici_objContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#allow_string.
    def visitAllow_string(self, ctx:MCONHWProfileParser.Allow_stringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#two_step.
    def visitTwo_step(self, ctx:MCONHWProfileParser.Two_stepContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#power_ctl.
    def visitPower_ctl(self, ctx:MCONHWProfileParser.Power_ctlContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#power_ctrl_args.
    def visitPower_ctrl_args(self, ctx:MCONHWProfileParser.Power_ctrl_argsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#pc_io.
    def visitPc_io(self, ctx:MCONHWProfileParser.Pc_ioContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#pc_active_low.
    def visitPc_active_low(self, ctx:MCONHWProfileParser.Pc_active_lowContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#pc_delay.
    def visitPc_delay(self, ctx:MCONHWProfileParser.Pc_delayContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#pc_timeout.
    def visitPc_timeout(self, ctx:MCONHWProfileParser.Pc_timeoutContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#ici_life_cycle_call.
    def visitIci_life_cycle_call(self, ctx:MCONHWProfileParser.Ici_life_cycle_callContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#ici_call_name.
    def visitIci_call_name(self, ctx:MCONHWProfileParser.Ici_call_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#ici_call_arg.
    def visitIci_call_arg(self, ctx:MCONHWProfileParser.Ici_call_argContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#pc_args.
    def visitPc_args(self, ctx:MCONHWProfileParser.Pc_argsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#boolean.
    def visitBoolean(self, ctx:MCONHWProfileParser.BooleanContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#AnObject.
    def visitAnObject(self, ctx:MCONHWProfileParser.AnObjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#EmptyObject.
    def visitEmptyObject(self, ctx:MCONHWProfileParser.EmptyObjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#ArrayOfValues.
    def visitArrayOfValues(self, ctx:MCONHWProfileParser.ArrayOfValuesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#EmptyArray.
    def visitEmptyArray(self, ctx:MCONHWProfileParser.EmptyArrayContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#pair.
    def visitPair(self, ctx:MCONHWProfileParser.PairContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#String.
    def visitString(self, ctx:MCONHWProfileParser.StringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#Atom.
    def visitAtom(self, ctx:MCONHWProfileParser.AtomContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#ObjectValue.
    def visitObjectValue(self, ctx:MCONHWProfileParser.ObjectValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by MCONHWProfileParser#ArrayValue.
    def visitArrayValue(self, ctx:MCONHWProfileParser.ArrayValueContext):
        return self.visitChildren(ctx)



del MCONHWProfileParser