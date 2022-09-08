import binaryninja
from .binja_go_symbol_restore_1_18 import restore_golang_symbols

binaryninja.plugin.PluginCommand.register("Restore Golang Symbols 1.18+",
                                          "Fix functions in Go 1.18+.",
                                          restore_golang_symbols)