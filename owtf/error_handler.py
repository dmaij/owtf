"""
owtf.error_handler
~~~~~~~~~~~~~~~~~~

The error handler provides a centralised control for aborting the application
and logging errors for debugging later.
"""

import logging
import traceback
import sys
import json

import requests

from owtf.dependency_management.dependency_resolver import BaseComponent
from owtf.dependency_management.interfaces import ErrorHandlerInterface
from owtf.lib.exceptions import FrameworkAbortException, PluginAbortException
from owtf.lib.general import cprint
from owtf.utils import OutputCleaner


class ErrorHandler(BaseComponent, ErrorHandlerInterface):
    command = ''
    len_padding = 100
    COMPONENT_NAME = "error_handler"

    def __init__(self):
        self.register_in_service_locator()
        self.core = None
        self.db = None
        self.db_error = None
        self.config = None
        self.padding = "\n%s\n\n" % ("_" * self.len_padding)
        self.sub_padding = "\n%s\n" % ("*" * self.len_padding)

    def init(self):
        """Initialize the components to load

        :return:
        :rtype:
        """
        self.core = self.get_component("core")
        self.db = self.get_component("db")
        self.db_error = self.get_component("db_error")
        self.config = self.get_component("config")

    def set_command(self, command):
        """Set a command in the error handler

        :param command: The command which resulted in the error
        :type command: `str`
        :return:
        :rtype: None
        """
        self.command = command

    def abort_framework(self, message):
        """Abort the OWTF framework.

        :warning: If it happens really early and :class:`framework.core.Core`
            has note been instanciated yet, `sys.exit()` is called with error
            code -1

        :param str message: Descriptive message about the abort.

        :return: full message explaining the abort.
        :rtype: str

        """
        message = "Aborted by Framework: %s" % message
        logging.error(message)
        if self.core is None:
            # core being None means that OWTF is aborting super early.
            # Therefore, force a brutal exit and throw away the message.
            sys.exit(-1)
        else:
            self.core.finish()
        return message

    def get_option_from_user(self, options):
        """Give the user options to select

        :param options: Set of available options for the user
        :type options: `str`
        :return: The different options for the user to choose from
        :rtype: `str`
        """
        return input("Options: 'e'+Enter= Exit %s, Enter= Next test\n" % options)

    def user_abort(self, level, partial_output=''):
        """This function handles the next steps when a user presses Ctrl-C

        :param level: The level which was aborted
        :type level: `str`
        :param partial_output: Partial output generated by the command or plugin
        :type partial_output: `str`
        :return: Message to present to the user
        :rtype: `str`
        """
        # Levels so far can be Command or Plugin
        logging.info("\nThe %s was aborted by the user: Please check the report and plugin output files" % level)
        message = ("\nThe %s was aborted by the user: Please check the report and plugin output files" % level)
        if level == 'Command':
            option = 'p'
            if option == 'e':
                # Try to save partial plugin results.
                raise FrameworkAbortException(partial_output)
            elif option == 'p':  # Move on to next plugin.
                # Jump to next handler and pass partial output to avoid losing results.
                raise PluginAbortException(partial_output)
        return message

    def log_error(self, message, trace=None):
        """Logs the error to the error DB and prints it to stdout

        :param message: Error message
        :type message: `str`
        :param trace: Traceback
        :type trace: `str`
        :return:
        :rtype: None
        """
        try:
            self.db_error.add(message, trace)  # Log error in the DB.
        except AttributeError:
            cprint("ERROR: DB is not setup yet: cannot log errors to file!")

    def add_new_bug(self, message):
        """Formats the bug to be reported by the auto-reporter

        :param message: Error message
        :type message: `str`
        :return:
        :rtype: None
        """
        exc_type, exc_value, exc_traceback = sys.exc_info()
        err_trace_list = traceback.format_exception(exc_type, exc_value, exc_traceback)
        err_trace = OutputCleaner.anonymise_command("\n".join(err_trace_list))
        message = OutputCleaner.anonymise_command(message)
        output = "OWTF BUG: Please report the sanitised information below to help make this better.Thank you"
        output += "\nMessage: %s\n" % message
        output += "\nError Trace:"
        output += "\n%s" % err_trace
        output += "\n%s" % self.padding
        cprint(output)
        self.log_error(message, err_trace)

    def add(self, message, type='owtf'):
        """Prints error to stdout or error db based on type

        :param message: Error message
        :type message: `str`
        :param type: Bug type
        :type type: `str`
        :return:
        :rtype: None
        """
        if type == 'owtf':
            return self.add_new_bug(message)
        else:
            output = self.padding + message + self.sub_padding
            cprint(output)
            self.log_error(message)

    def add_github_issue(self, username=None, title=None, body=None, id=None):
        """Adds the auto-formatted bug and creates an issue on Github

        :param username: Github handle of the user
        :type username: `str`
        :param title: Title for the issue to create
        :type title: `str`
        :param body: Error message and detailed bug description
        :type body: `str`
        :param id: bug to report
        :type id: `int`
        :return: The JSON response
        :rtype: `json`
        """
        if id is None or username is None:
            return False
        body += "\n\nSubmitted By - @"
        body += username
        data = {'title': title, 'body': body}
        data = json.dumps(data)  # Converted to string.
        headers = {
            "Content-Type": "application/json",
            "Authorization": "token " + self.config.get_val("GITHUB_BUG_REPORTER_TOKEN")
        }
        request = requests.post(self.config.get_val("GITHUB_API_ISSUES_URL"), headers=headers, data=data)
        response = request.json()
        if request.status_code == 201:
            self.db_error.update_after_github_report(id, body, True, response["html_url"])

        return response
