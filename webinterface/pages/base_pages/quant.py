"""Streamlit-based web interface for ProteoBench."""

import json
import logging
import uuid
from datetime import datetime
from pprint import pformat
from typing import Any, Dict, Optional

import pages.texts.proteobench_builder as pbb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit_utils
from pages.pages_variables.dda_quant_variables import VariablesDDAQuant
from streamlit_extras.let_it_rain import rain

from proteobench.io.parsing.parse_settings_ion import ParseSettingsBuilder
from proteobench.modules.dda_quant_ion.module import IonModule
from proteobench.utils.plotting.plot import PlotDataPoint

logger: logging.Logger = logging.getLogger(__name__)


class QuantUIObjects:
    """
    Main class for the Streamlit interface of ProteoBench quantification.

    This class handles the creation of the Streamlit UI elements, including the main page layout,
    input forms, results display, and data submission elements.
    """

    def __init__(
        self, variables_quant: VariablesDDAQuant, ionmodule: IonModule, parsesettingsbuilder: ParseSettingsBuilder
    ) -> None:
        """Initializes the Streamlit UI objects for the quantification modules."""
        # Assign instances of objects to class variables

        # Variables for dda quant specify var names and locations of texts, such as markdown files
        self.variables_quant: VariablesDDAQuant = variables_quant

        # IonModule is the main module for the quantification process (calculations, parsing, etc.)
        self.ionmodule: IonModule = ionmodule

        # ParseSettingsBuilder is used to build the parser settings for the input,
        # mainly used to get possible parsing options for the input file
        self.parsesettingsbuilder: ParseSettingsBuilder = parsesettingsbuilder

        # Initialize a dictionary to store user input
        self.user_input: Dict[str, Any] = dict()

        # Create page config and sidebar
        pbb.proteobench_page_config()
        pbb.proteobench_sidebar()

        # Make sure when initialized the submission is False
        if self.variables_quant.submit not in st.session_state:
            st.session_state[self.variables_quant.submit] = False

    def _create_text_header(self) -> None:
        """
        Creates the text header for the main page of the Streamlit UI. This includes the title,
        module description, input and configuration description.
        """
        st.title(self.variables_quant.texts.ShortMessages.title)
        if self.variables_quant.beta_warning:
            st.warning(
                "This module is in BETA phase. The figure presented below and the metrics calculation may change in the near future."
            )

        st.header("Description of the module")
        st.markdown(open(self.variables_quant.description_module_md, "r").read())
        st.header("Downloading associated files")
        st.markdown(open(self.variables_quant.description_files_md, "r").read(), unsafe_allow_html=True)
        st.header("Input and configuration")
        st.markdown(self.variables_quant.texts.ShortMessages.initial_results)

    def _create_main_submission_form(self) -> None:
        """
        Creates the main submission form for the Streamlit UI.
        This includes the input file uploader, additional parameters, and the main submission button.
        """

        with st.form(key="main_form"):
            # Input for the files and software used
            st.subheader("Input files")
            st.markdown(open(self.variables_quant.description_input_file_md, "r").read())
            self.user_input["input_format"] = st.selectbox(
                "Software tool",
                self.parsesettingsbuilder.INPUT_FORMATS,
                help=self.variables_quant.texts.Help.input_format,
            )

            self.user_input["input_csv"] = st.file_uploader(
                "Software tool result file", help=self.variables_quant.texts.Help.input_file
            )

            # Additional parameters not used for public submission, but displayed for the user
            st.markdown(self.variables_quant.texts.ShortMessages.initial_parameters)

            with st.expander("Additional parameters"):
                with open(self.variables_quant.additional_params_json) as file:
                    config = json.load(file)

                for key, value in config.items():
                    self.user_input[key] = self.generate_input_field(self.user_input["input_format"], value)

            st.markdown(self.variables_quant.texts.ShortMessages.run_instructions)

            # Submit button to start the benchmarking process
            submit_button = st.form_submit_button("Parse and bench", help=self.variables_quant.texts.Help.parse_button)

        ######################################################################
        # If data is submitted start resetting variables and run proteobench #
        ######################################################################

        if submit_button:
            if not self.user_input["input_csv"]:
                st.error(":x: Please provide a result file", icon="🚨")
                return
            if self.variables_quant.meta_file_uploader_uuid in st.session_state.keys():
                del st.session_state[self.variables_quant.meta_file_uploader_uuid]
            if self.variables_quant.comments_submission_uuid in st.session_state.keys():
                del st.session_state[self.variables_quant.comments_submission_uuid]
            if self.variables_quant.check_submission_uuid in st.session_state.keys():
                del st.session_state[self.variables_quant.check_submission_uuid]
            if self.variables_quant.button_submission_uuid in st.session_state.keys():
                del st.session_state[self.variables_quant.button_submission_uuid]
            self._run_proteobench()

    def _populate_results(self) -> None:
        """
        Populates the results section of the UI. This is called after data processing is complete.
        """
        self.generate_results("", None, None, False, None)

    def generate_input_field(self, input_format: str, content: dict) -> Any:
        """
        Generates input fields in the Streamlit UI based on the specified format and content.

        Args:
            input_format: The format of the input (e.g., 'text_input', 'number_input').
            content: Dictionary containing the configuration for the input field.

        Returns:
            A Streamlit widget corresponding to the specified input type.
        """
        if content["type"] == "text_area":
            if "placeholder" in content:
                return st.text_area(content["label"], placeholder=content["placeholder"], height=content["height"])
            elif "value" in content:
                return st.text_area(content["label"], content["value"][input_format], height=content["height"])
        if content["type"] == "text_input":
            if "placeholder" in content:
                return st.text_input(content["label"], placeholder=content["placeholder"])
            elif "value" in content:
                return st.text_input(content["label"], content["value"][input_format])
        if content["type"] == "number_input":
            return st.number_input(
                content["label"],
                value=None,
                format=content["format"],
                min_value=content["min_value"],
                max_value=content["max_value"],
            )
        if content["type"] == "selectbox":
            return st.selectbox(
                content["label"],
                content["options"],
                content["options"].index(content["value"][input_format]),
            )
        if content["type"] == "checkbox":
            return st.checkbox(content["label"], content["value"][input_format])

    def _init_slider(self) -> None:
        ##########################################
        # Initialize slider ID and default value #
        ##########################################

        if "slider_id" not in st.session_state.keys():
            st.session_state["slider_id"] = uuid.uuid4()
        if st.session_state["slider_id"] not in st.session_state.keys():
            st.session_state[st.session_state["slider_id"]] = self.variables_quant.default_val_slider

    def _create_results(self) -> None:
        #########################################
        # Creat the results section of the page #
        #########################################
        if self.variables_quant.all_datapoints in st.session_state or self.variables_quant.first_new_plot == False:
            return

        st.session_state[self.variables_quant.all_datapoints] = None
        st.session_state[self.variables_quant.all_datapoints] = self.ionmodule.obtain_all_data_point(
            st.session_state[self.variables_quant.all_datapoints]
        )
        if "slider_id" in st.session_state.keys():
            st.session_state[self.variables_quant.all_datapoints] = self.ionmodule.filter_data_point(
                st.session_state[self.variables_quant.all_datapoints],
                st.session_state[st.session_state["slider_id"]],
            )

        if (
            self.variables_quant.highlight_list not in st.session_state.keys()
            and "Highlight" not in st.session_state[self.variables_quant.all_datapoints].columns
        ):
            st.session_state[self.variables_quant.all_datapoints].insert(
                0, "Highlight", [False] * len(st.session_state[self.variables_quant.all_datapoints].index)
            )
        elif "Highlight" not in st.session_state[self.variables_quant.all_datapoints].columns:
            st.session_state[self.variables_quant.all_datapoints].insert(
                0, "Highlight", st.session_state[self.variables_quant.highlight_list]
            )

        if "slider_id" in st.session_state.keys():
            st.markdown(open(self.variables_quant.description_slider_md, "r").read())
            st.session_state[self.variables_quant.placeholder_slider] = st.empty()
            st.session_state[self.variables_quant.placeholder_slider].select_slider(
                label="Minimal ion quantifications (# samples)",
                options=[1, 2, 3, 4, 5, 6],
                value=st.session_state[st.session_state["slider_id"]],
                on_change=self.slider_callback,
                key=st.session_state["slider_id"],
            )

        st.session_state[self.variables_quant.placeholder_fig_compare] = st.empty()
        st.session_state[self.variables_quant.placeholder_table] = st.empty()
        st.session_state["table_id"] = uuid.uuid4()

        try:
            st.session_state[self.variables_quant.fig_metric] = PlotDataPoint.plot_metric(
                st.session_state[self.variables_quant.all_datapoints]
            )
        except Exception as e:
            st.error(f"Unable to plot the datapoints: {e}", icon="🚨")

        st.session_state[self.variables_quant.placeholder_fig_compare].plotly_chart(
            st.session_state[self.variables_quant.fig_metric], use_container_width=True
        )

        st.session_state[self.variables_quant.placeholder_table].data_editor(
            st.session_state[self.variables_quant.all_datapoints],
            key=st.session_state["table_id"],
            on_change=self.table_callback,
        )

    def make_submission_webinterface(self, params) -> Optional[str]:
        """
        Handles the submission process of the benchmark results to the ProteoBench repository.

        Args:
            params: Parameters used for the benchmarking.
            input_df: The input DataFrame.
            result_performance: DataFrame containing the performance results.

        Returns:
            The URL of the submission if successful, None otherwise.
        """

        # Make sure to set everything to submission ready
        st.session_state[self.variables_quant.submit] = True
        pr_url = None

        # Make a public submission button
        if self.variables_quant.button_submission_uuid in st.session_state.keys():
            button_submission_uuid = st.session_state[self.variables_quant.button_submission_uuid]
        else:
            button_submission_uuid = uuid.uuid4()
            st.session_state[self.variables_quant.button_submission_uuid] = button_submission_uuid
        submit_pr = st.button("I really want to upload it", key=button_submission_uuid)

        # If button is not pressed, return the pr_url (None)
        if not submit_pr:
            return pr_url

        # Obtain the user comments to add to the PR
        user_comments = self.user_input["comments_for_submission"]

        result_performance = st.session_state[self.variables_quant.result_performance_submission]

        # Remove the highlight column before submission
        if "Highlight" in st.session_state[self.variables_quant.all_datapoints_submission].columns:
            st.session_state[self.variables_quant.all_datapoints_submission].drop("Highlight", inplace=True, axis=1)

        # Make a pull request with the submission
        try:
            pr_url = self.ionmodule.clone_pr(
                st.session_state[self.variables_quant.all_datapoints_submission],
                params,
                st.secrets["gh"]["token"],
                username="Proteobot",
                remote_git="github.com/Proteobot/Results_Module2_quant_DDA.git",
                branch_name="new_branch",
                submission_comments=user_comments,
            )
        except Exception as e:
            st.error(f"Unable to create the pull request: {e}", icon="🚨")

        # Unable to create the PR, return None
        if not pr_url:
            del st.session_state[self.variables_quant.submit]
            return pr_url

        id = str(
            st.session_state[self.variables_quant.all_datapoints_submission][
                st.session_state[self.variables_quant.all_datapoints_submission]["old_new"] == "new"
            ].iloc[-1, :]["intermediate_hash"]
        )

        # Write the intermediate and input data to the storage directory (if available)
        if "storage" in st.secrets.keys():
            self.ionmodule.write_intermediate_raw(
                st.secrets["storage"]["dir"],
                id,
                st.session_state[self.variables_quant.input_df_submission],
                result_performance,
                self.user_input[self.variables_quant.meta_data],
            )

        return pr_url

    def successful_submission(self, pr_url) -> None:
        """
        Handles the UI updates and notifications after a successful submission of benchmark results.

        Args:
            pr_url: The URL of the submitted pull request.
        """
        if st.session_state[self.variables_quant.submit]:
            st.subheader("SUCCESS")
            st.markdown(self.variables_quant.texts.ShortMessages.submission_processing_warning)
            try:
                st.write(f"Follow your submission approval here: [{pr_url}]({pr_url})")
            except UnboundLocalError:
                # Happens when pr_url is not defined, e.g., local dev
                pass

            st.session_state[self.variables_quant.submit] = False
            rain(emoji="🎈", font_size=54, falling_speed=5, animation_length=1)

    def create_submission_elements(self) -> None:
        """
        Creates the UI elements necessary for data submission, including metadata uploader and comments section.
        """
        # Create a copy of the dataframes before submission, any changes made after submission will not be saved
        # to the dataframes shown to the user.
        if st.session_state[self.variables_quant.all_datapoints] is not None:
            st.session_state[self.variables_quant.all_datapoints_submission] = st.session_state[
                self.variables_quant.all_datapoints
            ].copy()
        if st.session_state[self.variables_quant.input_df] is not None:
            st.session_state[self.variables_quant.input_df_submission] = st.session_state[
                self.variables_quant.input_df
            ].copy()
        if st.session_state[self.variables_quant.result_perf] is not None:
            st.session_state[self.variables_quant.result_performance_submission] = st.session_state[
                self.variables_quant.result_perf
            ].copy()

        self.user_input[self.variables_quant.meta_data] = st.file_uploader(
            "Meta data for searches",
            help=self.variables_quant.texts.Help.meta_data_file,
            key=self.variables_quant.meta_file_uploader_uuid,
            accept_multiple_files=True,
        )

        self.user_input["comments_for_submission"] = st.text_area(
            "Comments for submission",
            placeholder=self.variables_quant.texts.ShortMessages.parameters_additional,
            height=200,
        )

        st.session_state[self.variables_quant.meta_data_text] = self.user_input["comments_for_submission"]

        st.session_state[self.variables_quant.check_submission] = st.checkbox(
            "I confirm that the metadata is correct",
        )

    def _run_proteobench(self) -> None:
        """
        Executes the ProteoBench benchmarking process. It handles the user's file submission,
        runs the benchmarking module, and updates the session state with the results.
        """
        st.header("Running Proteobench")
        status_placeholder = st.empty()
        status_placeholder.info(":hourglass_flowing_sand: Running Proteobench...")

        # Initialize the datapoints if it does not exist yet
        if self.variables_quant.all_datapoints not in st.session_state:
            st.session_state[self.variables_quant.all_datapoints] = None

        try:
            result_performance, all_datapoints, input_df = self.ionmodule.benchmarking(
                self.user_input["input_csv"],
                self.user_input["input_format"],
                self.user_input,
                st.session_state[self.variables_quant.all_datapoints],
                default_cutoff_min_prec=st.session_state[st.session_state["slider_id"]],
            )

            st.session_state[self.variables_quant.all_datapoints] = all_datapoints

            if "Highlight" not in st.session_state[self.variables_quant.all_datapoints].columns:
                st.session_state[self.variables_quant.all_datapoints].insert(
                    0, "Highlight", [False] * len(st.session_state[self.variables_quant.all_datapoints].index)
                )
            else:
                st.session_state[self.variables_quant.all_datapoints]["Highlight"] = [False] * len(
                    st.session_state[self.variables_quant.all_datapoints].index
                )
        except Exception as e:
            status_placeholder.error(":x: Proteobench ran into a problem")
            st.error(e, icon="🚨")
        else:
            # If update did not work we can still try to generate results
            self.generate_results(status_placeholder, result_performance, all_datapoints, True, input_df)

    def table_callback(self) -> None:
        """
        Callback function for handling edits made to the data table in the UI.
        It updates the session state to reflect changes made to the data points.
        """
        edits = st.session_state[st.session_state["table_id"]]["edited_rows"].items()
        for k, v in edits:
            try:
                st.session_state[self.variables_quant.all_datapoints][list(v.keys())[0]].iloc[k] = list(v.values())[0]
            except TypeError:
                return
        st.session_state[self.variables_quant.highlight_list] = list(
            st.session_state[self.variables_quant.all_datapoints]["Highlight"]
        )
        st.session_state[self.variables_quant.placeholder_table] = st.session_state[self.variables_quant.all_datapoints]

        # Plot any changes made to the data points
        try:
            fig_metric = PlotDataPoint.plot_metric(st.session_state[self.variables_quant.all_datapoints])
        except Exception as e:
            st.error(f"Unable to plot the datapoints: {e}", icon="🚨")

        st.session_state[self.variables_quant.fig_metric] = fig_metric

        if self.variables_quant.result_perf in st.session_state.keys():
            self.plots_for_current_data(True)

    def slider_callback(self) -> None:
        """
        Callback function for the slider input. It adjusts the data points displayed based on
        the selected slider value, such as the minimum number of ion quantifications.
        """
        st.session_state[self.variables_quant.all_datapoints] = self.ionmodule.filter_data_point(
            st.session_state[self.variables_quant.all_datapoints], st.session_state[st.session_state["slider_id"]]
        )

        try:
            fig_metric = PlotDataPoint.plot_metric(st.session_state[self.variables_quant.all_datapoints])
        except Exception as e:
            st.error(f"Unable to plot the datapoints: {e}", icon="🚨")

        st.session_state[self.variables_quant.fig_metric] = fig_metric

        if self.variables_quant.result_perf in st.session_state.keys():
            self.plots_for_current_data(True)

    def read_parameters(self) -> Any:
        """
        Reads and processes the parameter files provided by the user.

        Returns:
            The parameters read from the file, or None if there's an error.
        """
        params = None

        try:
            params = self.ionmodule.load_params_file(
                self.user_input[self.variables_quant.meta_data], self.user_input["input_format"]
            )
            st.text(f"Parsed and selected parameters:\n{pformat(params.__dict__)}")
        except KeyError as e:
            st.error("Parsing of meta parameters file for this software is not supported yet.", icon="🚨")
        except Exception as e:
            input_f = self.user_input["input_format"]
            st.error(
                f"Unexpected error while parsing file. Make sure you provided a meta parameters file produced by {input_f}: {e}",
                icon="🚨",
            )
        return params

    def create_sample_name(self) -> str:
        """
        Generates a unique sample name based on the input format, software version, and the current timestamp.

        Returns:
            A string representing the generated sample name.
        """
        time_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sample_name = "%s-%s-%s-%s" % (
            self.user_input["input_format"],
            self.user_input["software_version"],
            self.user_input["enable_match_between_runs"],
            time_stamp,
        )

        return sample_name

    def create_first_new_plot(self) -> None:
        """
        Generates and displays the initial plots and data tables based on the benchmark results.
        This includes setting up UI elements for displaying these results.
        """
        st.header("Results")
        st.subheader("Sample of the processed file")
        st.markdown(open(self.variables_quant.description_table_md, "r").read())
        st.session_state[self.variables_quant.df_head] = st.dataframe(
            st.session_state[self.variables_quant.result_perf].head(100)
        )

        st.markdown(st.markdown(open(self.variables_quant.description_results_md, "r").read()))

        st.subheader("Mean error between conditions")
        st.markdown(self.variables_quant.texts.ShortMessages.submission_result_description)

        sample_name = self.create_sample_name()

        st.markdown(open(self.variables_quant.description_slider_md, "r").read())
        # st.session_state["slider_id"] = uuid.uuid4()
        f = st.select_slider(
            label="Minimal ion quantifications (# samples)",
            options=[1, 2, 3, 4, 5, 6],
            value=st.session_state[st.session_state["slider_id"]],
            on_change=self.slider_callback,
            key=st.session_state["slider_id"],
        )

        st.session_state[self.variables_quant.all_datapoints] = self.ionmodule.filter_data_point(
            st.session_state[self.variables_quant.all_datapoints], st.session_state[st.session_state["slider_id"]]
        )

        try:
            st.session_state[self.variables_quant.fig_metric] = PlotDataPoint.plot_metric(
                st.session_state[self.variables_quant.all_datapoints]
            )
        except Exception as e:
            st.error(f"Unable to plot the datapoints: {e}", icon="🚨")

        placeholder_fig_compare = st.empty()
        placeholder_fig_compare.plotly_chart(
            st.session_state[self.variables_quant.fig_metric], use_container_width=True
        )
        st.session_state[self.variables_quant.placeholder_fig_compare] = placeholder_fig_compare

        st.session_state["table_id"] = uuid.uuid4()

        st.data_editor(
            st.session_state[self.variables_quant.all_datapoints],
            key=st.session_state["table_id"],
            on_change=self.table_callback,
        )

        st.subheader("Download calculated ratios")
        random_uuid = uuid.uuid4()
        st.download_button(
            label="Download",
            data=streamlit_utils.save_dataframe(st.session_state[self.variables_quant.result_perf]),
            file_name=f"{sample_name}.csv",
            mime="text/csv",
            key=f"{random_uuid}",
        )

        st.subheader("Add results to online repository")
        st.markdown(open(self.variables_quant.description_submission_md, "r").read())

    def call_later_plot(self) -> None:
        """
        Updates the plot data and UI elements after re-running the benchmark with new parameters or data.
        """
        fig_metric = st.session_state[self.variables_quant.fig_metric]
        st.session_state[self.variables_quant.fig_metric].data[0].x = fig_metric.data[0].x
        st.session_state[self.variables_quant.fig_metric].data[0].y = fig_metric.data[0].y

        st.session_state[self.variables_quant.placeholder_fig_compare].plotly_chart(
            st.session_state[self.variables_quant.fig_metric], use_container_width=True
        )

    def generate_results(
        self,
        status_placeholder: Any,
        result_performance: pd.DataFrame,
        all_datapoints: pd.DataFrame,
        recalculate: bool,
        input_df: pd.DataFrame,
    ) -> None:
        """
        Generates and displays the final results of the benchmark process. It updates the UI with plots,
        data tables, and other elements based on the benchmark results.

        Args:
            status_placeholder: UI element for displaying the processing status.
            result_performance: DataFrame with performance results.
            all_datapoints: DataFrame with all data points.
            recalculate: Boolean indicating whether the results need to be recalculated.
            input_df: DataFrame of the input data.
        """
        if recalculate:
            status_placeholder.success(":heavy_check_mark: Finished!")
            st.session_state[self.variables_quant.result_perf] = result_performance
            st.session_state[self.variables_quant.all_datapoints] = all_datapoints
            st.session_state[self.variables_quant.input_df] = input_df
        if not self.variables_quant.first_new_plot:
            st.session_state[self.variables_quant.df_head] = st.session_state[self.variables_quant.result_perf].head(
                100
            )

        st.session_state[self.variables_quant.fig_logfc] = self.plots_for_current_data(recalculate)

        if recalculate:
            try:
                st.session_state[self.variables_quant.fig_metric] = PlotDataPoint.plot_metric(
                    st.session_state[self.variables_quant.all_datapoints]
                )
            except Exception as e:
                st.error(f"Unable to plot the datapoints: {e}", icon="🚨")

        if self.variables_quant.first_new_plot:
            self.create_first_new_plot()
        else:
            self.call_later_plot()

        if all_datapoints is not None:
            st.session_state[self.variables_quant.all_datapoints] = all_datapoints
            st.session_state[self.variables_quant.input_df] = input_df

        # Create unique element IDs
        uuids = [
            self.variables_quant.meta_file_uploader_uuid,
            self.variables_quant.comments_submission_uuid,
            self.variables_quant.check_submission_uuid,
        ]

        for uuid_key in uuids:
            if uuid_key not in st.session_state:
                st.session_state[uuid_key] = uuid.uuid4()

        if self.variables_quant.first_new_plot:
            self.create_submission_elements()
        if self.user_input[self.variables_quant.meta_data]:
            params = self.read_parameters()
        if st.session_state[self.variables_quant.check_submission] and params != None:
            pr_url = self.make_submission_webinterface(params)
        if (
            st.session_state[self.variables_quant.check_submission]
            and params != None
            and self.variables_quant.submit in st.session_state
        ):
            self.successful_submission(pr_url)
        self.variables_quant.first_new_plot = False

    def plots_for_current_data(self, recalculate: bool) -> go.Figure:
        """
        Generates and returns plots based on the current benchmark data.

        Args:
            recalculate: Boolean to determine if the plot needs to be recalculated.

        Returns:
            A Plotly graph object containing the generated plot.
        """

        # filter result_performance dataframe on nr_observed column
        st.session_state[self.variables_quant.result_perf] = st.session_state[self.variables_quant.result_perf][
            st.session_state[self.variables_quant.result_perf]["nr_observed"]
            >= st.session_state[st.session_state["slider_id"]]
        ]

        if recalculate:
            parse_settings = self.parsesettingsbuilder.build_parser(self.user_input["input_format"])

            fig_logfc = PlotDataPoint.plot_fold_change_histogram(
                st.session_state[self.variables_quant.result_perf], parse_settings.species_expected_ratio()
            )
            fig_CV = PlotDataPoint.plot_CV_violinplot(st.session_state[self.variables_quant.result_perf])
            st.session_state[self.variables_quant.fig_cv] = fig_CV
            st.session_state[self.variables_quant.fig_logfc] = fig_logfc
        else:
            fig_logfc = st.session_state[self.variables_quant.fig_logfc]
            fig_CV = st.session_state[self.variables_quant.fig_cv]

        if self.variables_quant.first_new_plot:
            # Use st.beta_columns to arrange the figures side by side
            col1, col2 = st.columns(2)
            col1.subheader("Log2 Fold Change distributions by species.")
            col1.markdown(
                """
                    Left Panel : log2 fold changes calculated from your data
                """
            )
            col1.plotly_chart(fig_logfc, use_container_width=True)

            col2.subheader("Coefficient of variation distribution in Group A and B.")
            col2.markdown(
                """
                    Right Panel Panel : CV calculated from your data
                """
            )
            col2.plotly_chart(fig_CV, use_container_width=True)

        else:
            pass
        return fig_logfc


if __name__ == "__main__":
    logging.basicConfig(format="%(levelname)s:%(message)s", level=logging.INFO)
    QuantUIObjects()
