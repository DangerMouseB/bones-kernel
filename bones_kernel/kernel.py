# *******************************************************************************
#
#    Copyright (c) 2020 David Briant. All rights reserved.
#
# *******************************************************************************


# Useful references
# https://github.com/Calysto/metakernel/
# https://andrew.gibiansky.com/blog/ipython/ipython-kernels/
# https://jupyter-client.readthedocs.io/en/latest/kernels.html
# https://jupyter-client.readthedocs.io/en/stable/messaging.html


import sys, logging, traceback, ast
from coppertop import Pipeable, Missing, HookStdOutErrToLines
from ipykernel.kernelbase import Kernel
import datetime


STD_ERR = 'stderr'
STD_OUT = 'stdout'


MAGIC = '%%'    # %%python seams to cause Jupyter notebook to do python syntax highlighting :)
RESTART_CMD = 'restart'
DEFAULT_HANDLER = 'DEFAULT_HANDLER'
_knownCommands = [RESTART_CMD]

@Pipeable(rightToLeft=True)
def LogTo(logger, level, msg, **kwargs):
    logger.log(level, msg, **kwargs)

class _Dummy(object):pass
_logger = _Dummy()
_logger.error = LogTo(logging.getLogger(__name__), logging.ERROR)
_logger.warn = LogTo(logging.getLogger(__name__), logging.WARN)
_logger.info = LogTo(logging.getLogger(__name__), logging.INFO)
_logger.debug = LogTo(logging.getLogger(__name__), logging.DEBUG)
_logger.critical = LogTo(logging.getLogger(__name__), logging.CRITICAL)



class PythonHandler(object):

    def __init__(self):
        self._globals = {'_logger': _logger}

    def execute(self, src, kernel):
        #parseAstCompileAndExecute
        self._globals['_kernel'] = kernel
        astModule = ast.parse(src, mode='exec')
        values = []
        lastValue = Missing
        for i, each in enumerate(astModule.body):
            '%r: %r' % (i, type(each))
            if isinstance(each, ast.Expr):
                e = ast.Expression(each.value)   # change the ast.Expr into a ast.Expression which is suitable for eval
                bc = compile(e, filename="%r:%r" % (each.lineno, each.end_lineno), mode='eval')
                lastValue = eval(bc, self._globals)
                values.append(lastValue)
            else:
                m = ast.Module([each], astModule.type_ignores)
                bc = compile(m, filename="%r:%r" % (each.lineno, each.end_lineno), mode='exec')
                exec(bc, self._globals)
                lastValue = Missing
                values.append(lastValue)

        strippedSrc = src.strip()
        if strippedSrc:
            if strippedSrc[-1] == ';' or lastValue is Missing:
                return kernel.OK_SUPPRESS, values
            else:
                return kernel.OK, values
        else:
            return kernel.OK_SUPPRESS, values



def _splitSections(txt):
    # answers list of (magicLIne, section) where each section has prior lines as blank, so line-numbers are preserved in compiling, and magic blanked out
    sections = []
    currentSection = []
    lines = txt.splitlines()
    magic = DEFAULT_HANDLER
    for line in lines:
        if line.startswith(MAGIC):
            if currentSection:
                sections.append((magic, '\n'.join(currentSection)))
            currentSection = [''] * (len(currentSection))
            magic = line
            line = ''         # blank out the magic
        currentSection.append(line)
    if currentSection:
        sections.append((magic, '\n'.join(currentSection)))
    return sections



class SharedKernel(object):

    OK = 'OK'
    OK_SUPPRESS = 'OK_SUPPRESS'
    ERROR = 'ERROR'

    def __init__(self):
        self.handlers = {}
        self.handlers['python'] = PythonHandler()
        self.defaultHandler = None

    def restart(self, handlerName, kernel):
        # TODO - make restart call the restarterFn rather than be hardcoded
        if handlerName == 'python':
            self.handlers['python'] = PythonHandler()
            print('python started at %r' % datetime.datetime.now())
            return self.OK_SUPPRESS, []
        else:
            return self.ERROR, []



class MultiKernel(Kernel):
    # Kernel (the base class) takes the responsibility for incrementing execution_count so we don't have to

    implementation = 'multi_kernel'
    implementation_version = '0.1.0'
    banner = 'Welcome to Multi Kernel'
    language_info = {
        'name': 'multi_kernel',
        'mimetype': 'text/plain',
        # 'file_extension': '.bones',
    }


    def __init__(self, **kwargs):
        Kernel.__init__(self, **kwargs)
        self._sharedKernel = SharedKernel()
        # self.log.setLevel(logging.INFO)
        logging.basicConfig(format='%(asctime)s %(message)s', datefmt='%Y.%m.%d %I:%M:%S %p')
        if False:
            _logger.error = LogTo(self.log, logging.ERROR)
            _logger.warn = LogTo(self.log, logging.ERROR)
            _logger.info = LogTo(self.log, logging.ERROR)
            _logger.debug = LogTo(self.log, logging.ERROR)


    def do_execute(self, code, silent, store_history=True, user_expressions=None, allow_stdin=False):
        if silent or len(code.strip()) == 0:
            return self.execute_reply_ok()

        sectionNum = 0
        sections = _splitSections(code)
        for magicLine, sectionSrc in sections:
            sectionNum += 1
            with HookStdOutErrToLines() as stdouterrLines:
                try:
                    handlerId, method, arg, handler = Missing, Missing, Missing, Missing
                    if magicLine == DEFAULT_HANDLER:
                        handlerId = self._sharedKernel.defaultHandler
                        method = 'execute'
                        arg = sectionSrc
                        handler = self._sharedKernel.handlers.get(handlerId, None)
                    else:

                        # PARSE MAGIC
                        t = magicLine.split('%%')
                        if len(t) > 2:
                            raise SyntaxError("Invalid magic syntax '%s'" % magicLine)
                        tokens = t[1].split('_')
                        if tokens[0] in _knownCommands:
                            # of form %%knownCmd or %%knownCmd_arg
                            if len(tokens) > 2 or not tokens[0]:
                                raise SyntaxError("Invalid magic syntax '%s'" % magicLine)
                            handleId = 'kernel'
                            method = tokens[0]
                            arg = Missing if len(tokens) == 1 else tokens[1]
                            handler = self._sharedKernel
                        elif tokens[0] in self._sharedKernel.handlers:
                            # of form %%handlerName or %% handlerName_cmd
                            if len(tokens) == 1:
                                handlerId = tokens[0]
                                method = 'execute'
                                arg = sectionSrc
                                handler = self._sharedKernel.handlers[handlerId]
                            elif len(tokens) == 2:
                                handlerId = tokens[0]
                                method = tokens[1]
                                arg = sectionSrc
                                handler = self._sharedKernel.handlers[handlerId]
                            else:
                                if len(tokens) > 2 or not tokens[0]:
                                    raise SyntaxError("Invalid magic syntax '%s'" % magicLine)
                        else:
                            # of form %%unknownCmd or %%knownCmd_arg
                            if len(tokens) == 1:
                                handlerId = self._sharedKernel.defaultHandler
                                method = tokens[0]
                                arg = sectionSrc
                                handler = self._sharedKernel.handlers[handlerId]
                            elif len(tokens) == 2:
                                handlerId = self._sharedKernel.defaultHandler
                                method = tokens[0]
                                arg = tokens[1]
                                handler = self._sharedKernel.handlers[handlerId]
                            else:
                                if len(tokens) > 2 or not tokens[0]:
                                    raise SyntaxError("Invalid magic syntax '%s'" % magicLine)

                    if handler:
                        _logger.info(handlerId)
                        # call execute on the default if it exists
                        handlerFn = getattr(handler, method, None)
                        if handlerFn:

                            # HANDLE THE SECTION
                            outcome, values = handlerFn(arg, self._sharedKernel)

                            # TODO handle other mime types, e.g. for plotnine etc
                            if values:
                                if outcome == self._sharedKernel.OK:
                                    print(values[-1])
                                elif outcome == self._sharedKernel.ERROR:
                                    print(values[-1], file=sys.stderr)
                                elif outcome == self._sharedKernel.OK_SUPPRESS:
                                    pass
                        else:
                            print('%s (section %s) - %s has no handler fn %s' % (magicLine, sectionNum, handlerId, method), file=sys.stderr)
                    else:
                        if magicLine == DEFAULT_HANDLER:
                            print('No default handler defined', file=sys.stderr)
                        else:
                            if handlerId:
                                print('%s (section %s) - no handler found' % (magicLine, sectionNum), file=sys.stderr)
                            else:
                                print('%s (section %s) - Unknown magic' % (magicLine, sectionNum), file=sys.stderr)

                except Exception as ex:
                    t, v, tb = sys.exc_info()
                    traceback.print_exception(t, v, tb, file=sys.stderr)
                    print()

            stdoutLines, stderrLines = stdouterrLines
            if stdoutLines:
                if len(sections) > 1:
                    self.stream(STD_OUT, '[%s] %s\n' % (sectionNum, magicLine))
                self.stream(STD_OUT, '\n'.join(stdoutLines))
                self.stream(STD_OUT, '\n')
            if stderrLines:
                if len(sections) > 1:
                    self.stream(STD_ERR, '[%s] %s\n' % (sectionNum, magicLine))
                self.stream(STD_ERR, '\n'.join(stderrLines))
                self.stream(STD_ERR, '\n')

        return self.execute_reply_ok()



    def do_complete(self, code, cursor_pos):
        # for the moment use ' ' to break up tokens
        _logger.info << code << ", " << str(cursor_pos)
        return {
            'matches': ['fred', 'joe'],
            'cursor_start': 0,
            'cursor_end': cursor_pos,
            'metadata': dict(),
            'status': 'ok'
        }

    #     code = code[:cursor_pos]
    #     default = {'matches': [], 'cursor_start': 0,
    #                'cursor_end': cursor_pos, 'metadata': dict(),
    #                'status': 'ok'}
    #
    #     if not code or code[-1] == ' ':
    #         return default
    #
    #     tokens = code.replace(';', ' ').split()
    #     if not tokens:
    #         return default
    #
    #     matches = []
    #     token = tokens[-1]
    #     start = cursor_pos - len(token)
    #
    #     if token[0] == '$':
    #         # complete variables
    #         cmd = 'compgen -A arrayvar -A export -A variable %r' % token[1:] # strip leading $
    #         output = self.bashwrapper.run_command(cmd).rstrip()
    #         completions = set(output.split())
    #         # append matches including leading $
    #         matches.extend(['$'+c for c in completions])
    #     else:
    #         # complete functions and builtins
    #         cmd = 'compgen -cdfa %r' % token
    #         output = self.bashwrapper.run_command(cmd).rstrip()
    #         matches.extend(output.split())
    #
    #     if not matches:
    #         return default
    #     matches = [m for m in matches if m.startswith(token)]
    #
    #     return {'matches': sorted(matches), 'cursor_start': start,
    #             'cursor_end': cursor_pos, 'metadata': dict(),
    #             'status': 'ok'}


    def stream(self, name, text):
        self.send_response(
            self.iopub_socket,
            'stream',
            dict(
                name=name,
                text=text
            )
        )

    def execute_reply_ok(self):
        return dict(
            status='ok',
            execution_count=self.execution_count,
            payload=[],
            user_expressions={}
        )

    def execute_reply_error(self):
        return dict(
            status='error',
            execution_count=self.execution_count
        )



if __name__ == '__main__':
    from ipykernel.kernelapp import IPKernelApp
    IPKernelApp.launch_instance(kernel_class=MultiKernel)

