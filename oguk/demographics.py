"""
-------------------------------------------------------------------------------
Functions for generating demographic objects necessary for the OG-UK model
-------------------------------------------------------------------------------
"""
# Import packages
import os
import sys
import numpy as np
import pandas as pd
import eurostat
import cloudpickle
import pickle

# from og_uk_calibrate import parameter_plots as pp
from scipy.optimize import curve_fit
import scipy.optimize as opt
import matplotlib.pyplot as plt

# import xlsxwriter

# Create current directory path object
CUR_PATH = os.path.split(os.path.abspath(__file__))[0]

# Create demographic data directory path object
DATA_DIR = os.path.join(CUR_PATH, "data", "demographic")
if os.access(DATA_DIR, os.F_OK) is False:
    os.makedirs(DATA_DIR)

# Create demographic figures directory path object
FIG_DIR = os.path.join(CUR_PATH, "figures", "demographic")
if os.access(FIG_DIR, os.F_OK) is False:
    os.makedirs(FIG_DIR)

"""
-------------------------------------------------------------------------------
Define functions
-------------------------------------------------------------------------------
"""


def neg_exp_b_zerofunc(b, *args):
    """
    This is the zero function for the negative exponential as a function of
    parameter b that solves the following specification:

    BIRTHS_AGE = a * (AGE ** b) + c for AGE = Tp1_age, ... t_age_lastpos
    such that sum_{AGE=Tp1_age}^{t_age_lastpos}(a * (AGE ** b) +c) =
              births_last_bin,                                  [sum condition]
    and       a * b * T_age = T_births - Tm1_births,          [slope condition]
    and       a * ((T_age) ** b) + c = T_births             [connect condition]

    Args:
        b (scalar): exponent shape parameter
        args (tuple): arguments for zero function

    Returns:
        error_val (scalar): error value of zero function for given b
    """
    (
        T_age,
        Tm1_age,
        T_births,
        Tm1_births,
        Tp1_age,
        t_age_lastpos,
        births_last_bin,
    ) = args
    a = (T_births - Tm1_births) / ((T_age - Tm1_age) * (T_age * b))
    c = T_births - a * (T_age ** b)
    sum_age_exp_b = 0
    for age in range(Tp1_age, t_age_lastpos + 1):
        sum_age_exp_b += age ** b
    error_val = (
        a * sum_age_exp_b + (t_age_lastpos - Tp1_age + 1) * c - births_last_bin
    )

    return error_val


def get_fert(
    totpers,
    base_yr,
    min_yr,
    max_yr,
    download=False,
    save_data=False,
    graph=False,
):
    """
    This function generates a vector of fertility rates by model period
    age that corresponds to the fertility rate data by age in years
    using data from Eurostat.

    Args:
        totpers (int): total number of agent life periods (E+S), >= 3
        base_yr (int): year of data downloaded from Eurostat
        min_yr (int): age in years at which agents are born, >= 0
        max_yr (int): age in years at which agents die with certainty,
            >= 4
        download (bool): =True if want to download the data from Eurostat,
            otherwise load from saved data file
        save_data (bool): =True if want to save data used, should only be true
            if download=True
        graph (bool): =True if want graphical output

    Returns:
        fert_rates (Numpy array): fertility rates for each model period
            of life
    """
    Country = "UK"
    if base_yr > 2018:
        err_msg = (
            "Demographics.py ERROR: base_yr must be less-than-or "
            + "equal-to 2018."
        )
        ValueError(err_msg)
    Year = base_yr

    pop_age_data_path = os.path.join(DATA_DIR, "pop_age_data.csv")
    births_age_data_path = os.path.join(DATA_DIR, "births_age_data.csv")

    if download:
        # Download Eurostat Data - START
        StartPeriod = Year
        EndPeriod = Year

        # Download and clean population by age data
        filter_pars = {"GEO": [Country]}
        df_pop = eurostat.get_sdmx_data_df(
            "demo_pjan",
            StartPeriod,
            EndPeriod,
            filter_pars,
            flags=True,
            verbose=True,
        )

        # Remove totals and other unused rows
        indexNames = df_pop[
            (df_pop["AGE"] == "TOTAL")
            | (df_pop["AGE"] == "UNK")
            | (df_pop["AGE"] == "Y_OPEN")
        ].index
        df_pop.drop(indexNames, inplace=True)

        # Rename Y_LT1 to 0 (means 'less than one year')
        df_pop.AGE[df_pop.AGE == "Y_LT1"] = "Y0"

        #  Remove leading 'Y' from 'AGE' (e.g. 'Y23' --> '23')
        df_pop["AGE"] = df_pop["AGE"].str[1:]

        # Drop gender specific population, keep only total
        df_pop = df_pop[(df_pop["SEX"] == "T")]

        # Name of 1 column includes the year - create column name before dropping
        Obs_status_col = str(Year) + "_OBS_STATUS"
        # Drop columns except: Age, Frequency
        df_pop = df_pop.drop(
            columns=["UNIT", "SEX", "GEO", "FREQ", Obs_status_col]
        )

        # rename population total series "POP" instead of the year
        df_pop.rename(columns={Year: "POP"}, inplace=True)

        # convert AGE strings to int and Year strings to float
        df_pop = df_pop.astype(float)
        df_pop["AGE"] = df_pop["AGE"].astype(int)

        # sort values by AGE and reindex the DataFrame
        df_pop = df_pop.sort_values(by=["AGE"])
        df_pop.reset_index(drop=True, inplace=True)

        # Save the DataFrame
        if save_data:
            df_pop.to_csv(pop_age_data_path, index=False)

        # Download and clean births by age data
        df_births = eurostat.get_sdmx_data_df(
            "demo_fasec",
            StartPeriod,
            EndPeriod,
            filter_pars,
            flags=True,
            verbose=True,
        )

        # Select Sex = T (meaning "Total" of boys and girls born); drop others
        df_births = df_births[(df_births["SEX"] == "T")]

        # Drop columns except: Age, Frequency
        df_births = df_births.drop(
            columns=["UNIT", "SEX", "GEO", "FREQ", Obs_status_col]
        )
        # rename total births series "BIRTHS" instead of the year
        df_births.rename(columns={Year: "BIRTHS"}, inplace=True)

        # Remove remaining total and subtotals
        indexNames = df_births[
            (df_births["AGE"] == "TOTAL") |
            (df_births["AGE"] == "UNK") |
            (df_births["AGE"] == "Y15-19") |
            (df_births["AGE"] == "Y20-24") |
            (df_births["AGE"] == "Y25-29") |
            (df_births["AGE"] == "Y30-34") |
            (df_births["AGE"] == "Y35-39") |
            (df_births["AGE"] == "Y40-44") |
            (df_births["AGE"] == "Y45-49")
        ].index
        df_births.drop(indexNames, inplace=True)

        # Rename Y10-14 to Y14 and rename Y_GE50 to Y50
        df_births['AGE'].replace("Y10-14", "Y14", inplace=True)
        df_births['AGE'].replace("Y_GE50", "Y50", inplace=True)

        #  Remove leading 'Y' from 'AGE' (e.g. 'Y23' --> '23')
        df_births["AGE"] = df_births["AGE"].str[1:]
        # Convert AGE variable to int and reset index
        df_births["AGE"] = df_births["AGE"].astype(int)
        df_births.reset_index(drop=True, inplace=True)

        # Spread the births that were in Y_GE50 (now Y50) among ages 50 through
        # 57 (births=0 for age >=58) using a negative exponential function of
        # the form BIRTHS_AGE = a * (AGE ** b) + c for AGE = 50, 51, ... 57
        age_Tup = 49
        births_Tup = \
            df_births.loc[df_births["AGE"] == age_Tup,
                          "BIRTHS"].values.astype(float)[0]
        age_lastpos_up = 57
        age_max_up = 65
        births_lastbin_up = \
            df_births.loc[df_births['AGE'] == age_Tup + 1,
                          "BIRTHS"].values.astype(float)[0]
        bdup_args = (age_Tup, age_lastpos_up, age_max_up, births_Tup,
                     births_lastbin_up)
        age_vec_up, births_vec_up, abc_vec_up, age_lastpos_up = \
            distribute_bin(bdup_args)

        # populate births_50,...births_57 with estimated values
        for age in range(Tp1_age, t_age_lastpos + 1):
            df_fert['BIRTHS'][df_fert['AGE'] == age] = a * (age ** b) + c

        # sort values by AGE
        df_fert = df_fert.sort_values(by=["AGE"])
        if save_data:
            df_fert.to_csv(births_age_data_path, index=False)

    else:
        print("using csv saved population and births data by age")
        # Make sure the data files are accessible in DATA_DIR
        assert os.access(pop_age_data_path, os.F_OK)
        df_pop = pd.read_csv(pop_age_data_path, sep=",")
        assert os.access(births_age_data_path, os.F_OK)
        df_fert = pd.read_csv(births_age_data_path, sep=",")

    # Record values for 10-14 year old and over 50 year old for tail estimation
    under15total = (
        df_fert[Year].loc[df_fert["AGE"] == "Y10-14"].values.astype(float)
    )
    over50total = (
        df_fert[Year].loc[df_fert["AGE"] == "Y_GE50"].values.astype(float)
    )
    # Remove values for 10-14 year old and over 50 year old from main data
    indexNames = df_fert[
        (df_fert["AGE"] == "Y10-14") | (df_fert["AGE"] == "Y_GE50")
    ].index
    df_fert.drop(indexNames, inplace=True)

    # convert to numpy array, keeping only fertility values
    np_fert = df_fert[Year].to_numpy().astype(float)
    np_pop = df_pop[Year].to_numpy().astype(float)

    ############## Add tails for under 15 and over 50 - START ######
    # data contains single values for ages 10-14 & over 50
    # spread data from ages 10-14 and 50-60
    # using expontial function, based on shape of adjacent data

    # Top tail estimation:
    # select final 6 single-age values (ages 44-49)
    Y_44_49 = np_fert[-7:-1]
    x_44_49 = np.linspace(1, len(Y_44_49), len(Y_44_49))

    # define negative exponential curve
    def expon(x, a, b):
        return a * np.exp(-b * x)

    # estimate the best fit
    popt_top, pcov = curve_fit(expon, x_44_49, Y_44_49)

    # num_over50 is the number of years beyond age 49, e.g. 11 --> 50 to 60
    num_over50 = 11
    x_over50 = np.linspace(
        len(Y_44_49) + 1, len(Y_44_49) + num_over50, num_over50
    )

    # predict over 50 values based on estimated curve
    over50pred_unscaled = expon(x_over50, *popt_top)

    # scale predicted values to match the total over 50 births
    over50pred = over50pred_unscaled * over50total / over50pred_unscaled.sum()

    if graph:
        x_44_over50 = np.linspace(
            1, len(Y_44_49) + num_over50, len(Y_44_49) + num_over50
        )
        plt.title("Fertility data ages 44-49 and predictions ages 44-60")
        plt.plot(x_44_49, Y_44_49, "b-", label="fert data")
        plt.plot(
            x_44_over50,
            expon(x_44_over50, *popt_top),
            "r-",
            label="a.exp(-b x) fit: a=%5.3f, b=%5.3f" % tuple(popt_top),
        )
        plt.legend()
        plt.show()

    # Bottom tail estimation:
    # select initial 3 values (ages 15-17)
    # Note: taking more than 3 values misses the steep decline in the data
    Y_15_17 = np_fert[:3]
    Y_15_17 = np.flip(Y_15_17)
    x_15_17 = np.linspace(1, len(Y_15_17), len(Y_15_17))

    # estimate the best fit
    popt_low, pcov = curve_fit(expon, x_15_17, Y_15_17)

    # num_under15 is the number of years below age 15: ages 10-14
    num_under15 = 5
    x_under15 = np.linspace(
        len(Y_15_17) + 1, len(Y_15_17) + num_under15, num_under15
    )

    # predict under 15 values based on estimated curve
    under15pred_unscaled = expon(x_under15, *popt_low)

    # scale predicted values to match the total under 15 births
    under15pred = (
        under15pred_unscaled * under15total / under15pred_unscaled.sum()
    )
    under15pred = np.flip(under15pred)

    if graph:
        x_under15_17 = np.linspace(
            1, len(Y_15_17) + num_under15, len(Y_15_17) + num_under15
        )
        plt.title("Fertility data ages 17-15 and predictions ages 14-10")
        plt.plot(x_15_17, Y_15_17, "b-", label="fert data")
        plt.plot(
            x_under15_17,
            expon(x_under15_17, *popt_low),
            "r-",
            label="a.exp(-b x) fit: a=%5.3f, b=%5.3f" % tuple(popt_low),
        )
        plt.legend()
        plt.show()
    ############## Add tails for under 15 and over 50 - END ########

    ############## Calculate rate for all ages - START #############
    # extend fert to 100 ages with values for tails and zero elsewhere
    # under 15 year olds
    fert100 = np.hstack((under15pred, np_fert))
    fert100 = np.hstack((np.zeros(15 - num_under15), fert100))
    # over 50 year olds
    fert100 = np.hstack((fert100, over50pred))
    fert100 = np.hstack((fert100, np.zeros(50 - num_over50)))

    # convert to fertility rates per person
    fert_rates = fert100 / np_pop

    if graph:
        plt.title("Fertility rate by age per person")
        plt.plot(fert_rates)
        plt.show()
    ############## Calculate rate for all ages - END #############

    return fert_rates


def get_mort(
    totpers,
    min_age_yr,
    max_age_yr,
    beg_yr=2018,
    end_yr=2018,
    download=False,
    save_data=False,
    graph=False,
):
    """
    This function generates a vector of mortality rates by model period age.
    Source: Eurostat demographic data using the Eurostat Python package
            https://pypi.org/project/eurostat/

    Args:
        totpers (int): total number of agent life periods (E+S), >= 3
        min_age_yr (int): age in years at which agents are born, >= 0
        max_age_yr (int): age in years at which agents die with certainty,
            > min_age_yr. For example, max_age_yr = 100 means that a model
            agent dies at the beginning of the year in which they turn 100 (at
            the end of their 99th year)
        download (bool): =True to download data from Eurostat. Otherwise, load
            data from mort_rate_data.csv in DATA_DIR
        save_data (bool): =True and download=True then save df_mort DataFrame
            as mort_rate_data.csv file in DATA_DIR
        graph (bool): =True if want graphical output

    Returns:
        mort_rates (Numpy array): mortality rates that correspond to each model
            period of life
        infmort_rate (scalar): infant mortality rate
    """
    # The infant mortality rate in the U.K. is reported to be 3.507 deaths per
    # 1,000 live births in 2021 (see https://www.macrotrends.net/countries/...
    # GBR/united-kingdom/infant-mortality-rate).
    infmort_rate = 3.507 / 1000

    if download:
        # Get U.K. mortality rate and total population data from Eurostat and
        # clean it
        country = "UK"
        mort_data_beg_yr = beg_yr
        mort_data_end_yr = end_yr
        pop_data_beg_yr = beg_yr
        pop_data_end_yr = end_yr
        filter_pars = {"GEO": [country]}
        df_mort = eurostat.get_sdmx_data_df(
            "demo_magec",
            mort_data_beg_yr,
            mort_data_end_yr,
            filter_pars,
            flags=True,
            verbose=True,
        )
        df_pop = eurostat.get_sdmx_data_df(
            "demo_pjan",
            pop_data_beg_yr,
            pop_data_end_yr,
            filter_pars,
            flags=True,
            verbose=True,
        )
        # Delete columns that we don't use (keep only columns that do use)
        df_mort = df_mort[["SEX", "AGE", beg_yr]]
        df_pop = df_pop[["SEX", "AGE", beg_yr]]
        # Rename the total deaths column, and the other columns
        df_mort.rename(
            columns={"SEX": "sex", "AGE": "age_str", beg_yr: "tot_deaths"},
            inplace=True,
        )
        df_pop.rename(
            columns={"SEX": "sex", "AGE": "age_str", beg_yr: "tot_pop"},
            inplace=True,
        )
        # Keep only all gender ('T') deaths and population by age
        df_mort = df_mort[df_mort["sex"] == "T"]
        df_pop = df_pop[df_pop["sex"] == "T"]
        # Now drop 'sex' variable
        df_mort = df_mort[["age_str", "tot_deaths"]]
        df_pop = df_pop[["age_str", "tot_pop"]]
        # Drop the age categories that we don't use ('TOTAL', 'UNK', 'Y_OPEN')
        indexNames_mort = df_mort[
            (df_mort["age_str"] == "TOTAL")
            | (df_mort["age_str"] == "UNK")
            | (df_mort["age_str"] == "Y_OPEN")
            | (df_mort["age_str"] == "Y_LT5")
            | (df_mort["age_str"] == "Y5-9")
            | (df_mort["age_str"] == "Y10-14")
            | (df_mort["age_str"] == "Y15-19")
            | (df_mort["age_str"] == "Y20-24")
            | (df_mort["age_str"] == "Y25-29")
            | (df_mort["age_str"] == "Y30-34")
            | (df_mort["age_str"] == "Y35-39")
            | (df_mort["age_str"] == "Y40-44")
            | (df_mort["age_str"] == "Y45-49")
            | (df_mort["age_str"] == "Y50-54")
            | (df_mort["age_str"] == "Y55-59")
            | (df_mort["age_str"] == "Y60-64")
            | (df_mort["age_str"] == "Y65-69")
            | (df_mort["age_str"] == "Y70-74")
            | (df_mort["age_str"] == "Y75-79")
            | (df_mort["age_str"] == "Y80-84")
            | (df_mort["age_str"] == "Y85-89")
            | (df_mort["age_str"] == "Y_GE90")
        ].index
        df_mort.drop(indexNames_mort, inplace=True)
        indexNames_pop = df_pop[
            (df_pop["age_str"] == "TOTAL")
            | (df_pop["age_str"] == "UNK")
            | (df_pop["age_str"] == "Y_OPEN")
        ].index
        df_pop.drop(indexNames_pop, inplace=True)
        # Rename age='Y_LT1' to 'Y0'
        df_mort.age_str[df_mort.age_str == "Y_LT1"] = "Y0"
        df_pop.age_str[df_pop.age_str == "Y_LT1"] = "Y0"
        # Generate new age variable that is numeric (remove 'Y' prefix)
        df_mort["age"] = df_mort["age_str"].str[1:].astype(int)
        df_pop["age"] = df_pop["age_str"].str[1:].astype(int)
        # Remove age_str variable and sort DataFrame by age
        df_mort = df_mort[["age", "tot_deaths"]]
        df_mort = df_mort.sort_values(by=["age"])
        df_mort.reset_index(drop=True, inplace=True)
        df_pop = df_pop[["age", "tot_pop"]]
        df_pop = df_pop.sort_values(by=["age"])
        df_pop.reset_index(drop=True, inplace=True)
        # Merge total population data into total deaths data
        df_mort = pd.merge(df_mort, df_pop, on="age", validate="1:1")
        # Change 'tot_deaths' and 'tot_pop' to numeric float
        df_mort["tot_deaths"] = df_mort["tot_deaths"].astype(np.float64)
        df_mort["tot_pop"] = df_mort["tot_pop"].astype(np.float64)
        # Create mortality rates variable
        df_mort["mort_rate_yr_data"] = np.divide(
            df_mort["tot_deaths"], df_mort["tot_pop"]
        )
        # Set the mortality rate in max_age_yr = 1.0
        df_mort["mort_rate_yr_mod"] = df_mort["mort_rate_yr_data"]
        df_mort.loc[df_mort["age"] == max_age_yr - 1, "mort_rate_yr_mod"] = 1.0
        if save_data:
            mort_data_csv_path = os.path.join(DATA_DIR, "mort_rate_data.csv")
            df_mort.to_csv(mort_data_csv_path, index=False)

    else:
        mort_data_csv_path = os.path.join(DATA_DIR, "mort_rate_data.csv")
        assert os.access(mort_data_csv_path, os.F_OK)
        df_mort = pd.read_csv(mort_data_csv_path)

    # Create the model-ages mort_rates variable
    if totpers == 100 and min_age_yr == 0 and max_age_yr == 100:
        # This is case in which model age periods correspond to years
        mort_rates = df_mort["mort_rate_yr_mod"].to_numpy()

    else:
        # This is case in which model age periods do not correspond to years or
        # in which the initial age does not start at 0 and the ending age does
        # not end at 100
        yr_cut_pts = np.linspace(min_age_yr, max_age_yr, totpers + 1)

        tot_deaths = np.zeros(totpers)
        tot_pop = np.zeros(totpers)
        for per in range(totpers):
            # Get relevant vector of total deaths yearly data
            deaths_yr_data = df_mort["tot_deaths"][
                (
                    (df_mort["age"] >= np.floor(yr_cut_pts[per]))
                    & (df_mort["age"] <= np.ceil(yr_cut_pts[per + 1]))
                )
            ].to_numpy()
            # Get relevant vector of total population yearly data
            totpop_yr_data = df_mort["tot_pop"][
                (
                    (df_mort["age"] >= np.floor(yr_cut_pts[per]))
                    & (df_mort["age"] <= np.ceil(yr_cut_pts[per + 1]))
                )
            ].to_numpy()
            # Calculate the percent of the first and last bins to be included
            # in totals
            pct_first_yr_bin = 1 - (
                yr_cut_pts[per] - np.floor(yr_cut_pts[per])
            )
            pct_last_yr_bin = 1 - (
                np.ceil(yr_cut_pts[per + 1]) - yr_cut_pts[per + 1]
            )
            # Calculate total deaths in model age period
            deaths_yr_data[0] = pct_first_yr_bin * deaths_yr_data[0]
            deaths_yr_data[-1] = pct_last_yr_bin * deaths_yr_data[-1]
            tot_deaths[per] = deaths_yr_data.sum()
            # Calculate total population in model age period
            totpop_yr_data[0] = pct_first_yr_bin * totpop_yr_data[0]
            totpop_yr_data[-1] = pct_last_yr_bin * totpop_yr_data[-1]
            tot_pop[per] = totpop_yr_data.sum()

        mort_rates = tot_deaths / tot_pop
        mort_rates[-1] = 1.0

    if graph:
        mort_rates_yr = df_mort["mort_rate_yr_data"].to_numpy()
        ages_yr = np.arange(0, 100)
        # pp.plot_mort_rates_data(
        #     totpers,
        #     min_age_yr,
        #     max_age_yr,
        #     mort_rates_yr,
        #     ages_yr,
        #     mort_rates,
        #     infmort_rate,
        #     output_dir=FIG_DIR,
        # )

    return mort_rates, infmort_rate


def get_imm_resid(
    totpers,
    min_yr,
    max_yr,
    base_yr,
    download=False,
    save_data=True,
    graph=False,
):
    """
    Calculate immigration rates by age as a residual given population
    levels in different periods, then output average calculated
    immigration rate. We have to replace the first mortality rate in
    this function in order to adjust the first implied immigration rate
    (Source: Population data come Census National Population Characteristics
    2010-2019, Annual Estimates of the Resident Population by Single
    Year of Age and Sex for the United States: April 1, 2010 to
    July 1, 2019 (NC-EST2019-AGESEX-RES))

    Args:
        totpers (int): total number of agent life periods (E+S), >= 3
        min_yr (int): age in years at which agents are born, >= 0
        max_yr (int): age in years at which agents die with certainty,
            >= 4
        graph (bool): =True if want graphical output

    Returns:
        imm_rates (Numpy array):immigration rates that correspond to
            each period of life, length E+S

    """

    ##### download previous years of population - START ############
    Country = "UK"
    StartPeriod = 2015
    EndPeriod = base_yr

    if download:
        filter_pars = {"GEO": [Country]}
        df_pop = eurostat.get_sdmx_data_df(
            "demo_pjan",
            StartPeriod,
            EndPeriod,
            filter_pars,
            flags=True,
            verbose=True,
        )

        # Remove totals and other unused rows
        indexNames = df_pop[
            (df_pop["AGE"] == "TOTAL")
            | (df_pop["AGE"] == "UNK")
            | (df_pop["AGE"] == "Y_OPEN")
        ].index
        df_pop.drop(indexNames, inplace=True)

        # Rename Y_LT1 to 0 (means 'less than one year')
        df_pop.AGE[df_pop.AGE == "Y_LT1"] = "Y0"

        # Remove leading 'Y' from 'AGE' (e.g. 'Y23' --> '23')
        df_pop["AGE"] = df_pop["AGE"].str[1:]

        # Use total population, to calculate fertility per person
        df_pop = df_pop[(df_pop["SEX"] == "T")]

        # Name of 1 column includes the year - create column name before dropping
        Obs_status_col = str(base_yr) + "_OBS_STATUS"
        # Drop columns except: Age, Frequency
        df_pop = df_pop.drop(
            columns=["UNIT", "SEX", "GEO", "FREQ", Obs_status_col]
        )
        if save_data:
            pop_imm_data_csv_path = os.path.join(
                DATA_DIR, "pop_imm_rate_data.csv"
            )
            df_pop.to_csv(pop_imm_data_csv_path, index=False)

    else:
        pop_imm_data_csv_path = os.path.join(DATA_DIR, "pop_imm_rate_data.csv")
        assert os.access(pop_imm_data_csv_path, os.F_OK)
        df_pop = pd.read_csv(pop_imm_data_csv_path)

    if StartPeriod != base_yr:
        num_yr = base_yr - StartPeriod
        for n in range(1, num_yr + 1):
            print("n: ", n)
            Obs_status_col_SP = str(base_yr - n) + "_OBS_STATUS"
            df_pop = df_pop.drop(columns=[Obs_status_col_SP])
    df_pop = df_pop.astype(float)
    df_pop = df_pop.sort_values(by=["AGE"])
    if download:
        np_pop = df_pop[base_yr].to_numpy().astype(float)
    else:
        np_pop = df_pop[str(base_yr)].to_numpy().astype(float)

    if StartPeriod != base_yr:
        num_yr = base_yr - StartPeriod
        np_pop_prev = np.zeros((len(np_pop), num_yr))
        for n in range(1, num_yr + 1):
            if download:
                np_pop_prev[:, n - 1] = (
                    df_pop[base_yr - n].to_numpy().astype(float)
                )
            else:
                np_pop_prev[:, n - 1] = (
                    df_pop[str(base_yr - n)].to_numpy().astype(float)
                )

    ##### download previous year population - END ############

    # Create three years of estimated immigration rates for youngest age
    # individuals
    imm_mat = np.zeros((3, totpers))
    # years 2017,2016,2015:
    pop11vec = np_pop_prev[0, :].transpose()
    # years 2018,2017,2016:
    pop21vec = np.zeros(3)
    pop21vec = np.vstack((np_pop[0], np_pop_prev[0, 0], np_pop_prev[0, 1])).T

    # download total new borns in 2015,2016,2017
    Country = "UK"
    Year = base_yr
    StartPeriod = 2015
    EndPeriod = Year
    Total = "TOTAL"
    Gender = "T"
    if download:
        filter_pars = {"GEO": [Country], "AGE": [Total], "SEX": [Gender]}
        df_fert_total = eurostat.get_sdmx_data_df(
            "demo_fasec",
            StartPeriod,
            EndPeriod,
            filter_pars,
            flags=True,
            verbose=True,
        )
        newbornvec = np.vstack(
            (
                df_fert_total[2017]
                .loc[df_fert_total["AGE"] == "TOTAL"]
                .values.astype(float),
                df_fert_total[2016]
                .loc[df_fert_total["AGE"] == "TOTAL"]
                .values.astype(float),
                df_fert_total[2015]
                .loc[df_fert_total["AGE"] == "TOTAL"]
                .values.astype(float),
            )
        ).T
        if save_data:
            newbornvec_csv_path = os.path.join(DATA_DIR, "newbornvec.csv")
            np.savetxt(newbornvec_csv_path, newbornvec, delimiter=",")
    else:
        newbornvec_csv_path = os.path.join(DATA_DIR, "newbornvec.csv")
        assert os.access(newbornvec_csv_path, os.F_OK)
        newbornvec = np.genfromtxt(newbornvec_csv_path, delimiter=",")

    imm_mat[:, 0] = (pop21vec - newbornvec) / pop11vec

    mort_rates, infmort_rate = get_mort(
        totpers,
        min_yr,
        max_yr,
        beg_yr=base_yr,
        end_yr=base_yr,
        download=False,
        save_data=False,
        graph=False,
    )

    # Estimate 3 years of immigration rates for all other-aged
    # individuals
    pop16mat = np.vstack(
        # (pop_2016_EpS[:-1], pop_2017_EpS[:-1], pop_2018_EpS[:-1])
        (np_pop_prev[:-1, 0], np_pop_prev[:-1, 1], np_pop_prev[:-1, 2])
    )
    pop17mat = np.vstack(
        # (pop_2016_EpS[1:], pop_2017_EpS[1:], pop_2018_EpS[1:])
        (np_pop_prev[1:, 2], np_pop_prev[1:, 1], np_pop_prev[1:, 0])
    )
    pop18mat = np.vstack(
        # (pop_2017_EpS[1:], pop_2018_EpS[1:], pop_2019_EpS[1:])
        (np_pop_prev[1:, 1], np_pop_prev[1:, 0], np_pop[1:])
    )

    mort_mat = np.tile(mort_rates[:-1], (3, 1))
    imm_mat[:, 1:] = (pop18mat - (1 - mort_mat) * pop16mat) / pop17mat
    # Final estimated immigration rates are the averages over 3 years
    imm_rates = imm_mat.mean(axis=0)

    # imm_rates for older ages clearly unreliable (small sample, not reconciled)
    # replace ages 90+ with average value for ages 80-89
    imm_rates_80s = imm_rates[80:89].sum() / 10
    imm_rates[90:] = imm_rates_80s

    # take moving averages to smooth
    imm_rates_smooth = np.zeros(totpers)
    for i in range(totpers):
        if (i == 0) or (i == (totpers - 1)):
            imm_rates_smooth[i] = imm_rates[i]
        else:
            imm_rates_smooth[i] = (
                imm_rates[i - 1] + imm_rates[i] + imm_rates[i + 1]
            ) / 3
    imm_rates = imm_rates_smooth

    if graph:
        plt.title(
            "imm_rates by age per pers. (new born recalc & 90s=ave80s & smoothed"
        )
        plt.plot(imm_rates)
        plt.show()

    return imm_rates


def immsolve(imm_rates, *args):
    """
    This function generates a vector of errors representing the
    difference in two consecutive periods stationary population
    distributions. This vector of differences is the zero-function
    objective used to solve for the immigration rates vector, similar to
    the original immigration rates vector from get_imm_resid(), that
    sets the steady-state population distribution by age equal to the
    population distribution in period int(1.5*S)

    Args:
        imm_rates (Numpy array):immigration rates that correspond to
            each period of life, length E+S
        args (tuple): (fert_rates, mort_rates, infmort_rate, omega_cur,
            g_n_SS)

    Returns:
        omega_errs (Numpy array): difference between omega_new and
            omega_cur_pct, length E+S

    """
    # TO DO: Test immsolve from get_pop_objs
    fert_rates, mort_rates, infmort_rate, omega_cur_lev, g_n_SS = args
    omega_cur_pct = omega_cur_lev / omega_cur_lev.sum()
    totpers = len(fert_rates)
    OMEGA = np.zeros((totpers, totpers))
    OMEGA[0, :] = (1 - infmort_rate) * fert_rates + np.hstack(
        (imm_rates[0], np.zeros(totpers - 1))
    )
    OMEGA[1:, :-1] += np.diag(1 - mort_rates[:-1])
    OMEGA[1:, 1:] += np.diag(imm_rates[1:])
    omega_new = np.dot(OMEGA, omega_cur_pct) / (1 + g_n_SS)
    omega_errs = omega_new - omega_cur_pct

    return omega_errs


def get_pop_objs(
    E,
    S,
    T,
    min_yr,
    max_yr,
    base_yr,
    curr_year,
    download=True,
    save_data=True,
    GraphDiag=False,
):
    """
    This function produces the demographics objects to be used in the
    OG-UK model package.

    Args:
        E (int): number of model periods in which agent is not
            economically active, >= 1
        S (int): number of model periods in which agent is economically
            active, >= 3
        T (int): number of periods to be simulated in TPI, > 2*S
        min_yr (int): age in years at which agents are born, >= 0
        max_yr (int): age in years at which agents die with certainty,
            >= 4
        base_yr (int): year of demographic data to be used or downloaded
        curr_year (int): current year for which analysis will begin,
            >= 2016
        GraphDiag (bool): =True if want graphical output and printed
                diagnostics

    Returns:
        pop_dict (dict): includes:
            omega_path_S (Numpy array), time path of the population
                distribution from the current state to the steady-state,
                size T+S x S
            g_n_SS (scalar): steady-state population growth rate
            omega_SS (Numpy array): normalized steady-state population
                distribution, length S
            surv_rates (Numpy array): survival rates that correspond to
                each model period of life, length S
            mort_rates (Numpy array): mortality rates that correspond to
                each model period of life, length S
            g_n_path (Numpy array): population growth rates over the time
                path, length T + S

    """
    assert curr_year >= 2019

    fert_rates = get_fert(E + S, base_yr, min_yr, max_yr, graph=False)
    mort_rates, infmort_rate = get_mort(
        E + S,
        min_yr,
        max_yr,
        beg_yr=2018,
        end_yr=2018,
        graph=False,
    )
    mort_rates_S = mort_rates[-S:]
    imm_rates_orig = get_imm_resid(E + S, min_yr, max_yr, base_yr, graph=False)

    OMEGA_orig = np.zeros((E + S, E + S))
    OMEGA_orig[0, :] = fert_rates + np.hstack(
        (imm_rates_orig[0], np.zeros(E + S - 1))
    )
    OMEGA_orig[1:, :-1] += np.diag(1 - mort_rates[:-1])
    OMEGA_orig[1:, 1:] += np.diag(imm_rates_orig[1:])

    # Solve for steady-state population growth rate and steady-state
    # population distribution by age using eigenvalue and eigenvector
    # decomposition
    eigvalues, eigvectors = np.linalg.eig(OMEGA_orig)
    g_n_SS = (eigvalues[np.isreal(eigvalues)].real).max() - 1
    eigvec_raw = eigvectors[
        :, (eigvalues[np.isreal(eigvalues)].real).argmax()
    ].real
    omega_SS_orig = eigvec_raw / eigvec_raw.sum()

    ##### download previous year population - START ############
    Country = "UK"
    Year = 2018
    StartPeriod = 2015
    EndPeriod = Year

    if download:
        filter_pars = {"GEO": [Country]}
        df_pop = eurostat.get_sdmx_data_df(
            "demo_pjan",
            StartPeriod,
            EndPeriod,
            filter_pars,
            flags=True,
            verbose=True,
        )

        # Remove totals and other unused rows
        indexNames = df_pop[
            (df_pop["AGE"] == "TOTAL")
            | (df_pop["AGE"] == "UNK")
            | (df_pop["AGE"] == "Y_OPEN")
        ].index
        df_pop.drop(indexNames, inplace=True)

        # Rename Y_LT1 to 0 (means 'less than one year')
        df_pop.AGE[df_pop.AGE == "Y_LT1"] = "Y0"

        # Remove leading 'Y' from 'AGE' (e.g. 'Y23' --> '23')
        df_pop["AGE"] = df_pop["AGE"].str[1:]

        # Use total population, to calculate fertility per person
        df_pop = df_pop[(df_pop["SEX"] == "T")]

        # Name of 1 column includes the year - create column name before dropping
        Obs_status_col = str(Year) + "_OBS_STATUS"
        # Drop columns except: Age, Frequency
        df_pop = df_pop.drop(
            columns=["UNIT", "SEX", "GEO", "FREQ", Obs_status_col]
        )

        if StartPeriod != Year:
            num_yr = Year - StartPeriod
            for n in range(1, num_yr + 1):
                print("n: ", n)
                Obs_status_col_SP = str(Year - n) + "_OBS_STATUS"
                df_pop = df_pop.drop(columns=[Obs_status_col_SP])

        # convert strings to float
        df_pop = df_pop.astype(float)

        # sort values by AGE
        df_pop = df_pop.sort_values(by=["AGE"])

        np_pop = df_pop[Year].to_numpy().astype(float)
        if save_data:
            np_pop_csv_path = os.path.join(DATA_DIR, "np_pop.csv")
            np.savetxt(np_pop_csv_path, np_pop, delimiter=",")
            df_pop_csv_path = os.path.join(DATA_DIR, "df_pop_data.csv")
            df_pop.to_csv(df_pop_csv_path, index=False)

    else:
        np_pop_csv_path = os.path.join(DATA_DIR, "np_pop.csv")
        assert os.access(np_pop_csv_path, os.F_OK)
        np_pop = np.genfromtxt(np_pop_csv_path, delimiter=",")
        print("np_pop: ", np_pop)
        print("type np_pop: ", type(np_pop))
        df_pop_csv_path = os.path.join(DATA_DIR, "df_pop_data.csv")
        assert os.access(df_pop_csv_path, os.F_OK)
        df_pop = pd.read_csv(df_pop_csv_path)

    if StartPeriod != Year:
        num_yr = Year - StartPeriod
        np_pop_prev = np.zeros((len(np_pop), num_yr))
        for n in range(1, num_yr + 1):
            if download:
                np_pop_prev[:, n - 1] = (
                    df_pop[Year - n].to_numpy().astype(float)
                )
            else:
                np_pop_prev[:, n - 1] = (
                    df_pop[str(Year - n)].to_numpy().astype(float)
                )
            print("np_pop_prev[-20:]: ", np_pop_prev[-20:, n - 1])
            print("np_pop_prev.shape: ", np_pop_prev.shape)
    ##### download previous year population - END ############

    # Generate time path of the nonstationary population distribution
    omega_path_lev = np.zeros((E + S, T + S))

    # Age most recent population data to the current year of analysis
    # pop_curr = pop_2019_EpS.copy()
    pop_curr = np_pop
    data_year = 2018
    curr_year = 2018
    pop_next = np.dot(OMEGA_orig, pop_curr)
    g_n_curr = (pop_next[-S:].sum() - pop_curr[-S:].sum()) / pop_curr[
        -S:
    ].sum()  # g_n in 2019
    pop_past = pop_curr  # assume 2018-2019 pop
    # Age the data to the current year
    for per in range(curr_year - data_year):
        pop_next = np.dot(OMEGA_orig, pop_curr)
        g_n_curr = (pop_next[-S:].sum() - pop_curr[-S:].sum()) / pop_curr[
            -S:
        ].sum()
        pop_past = pop_curr
        pop_curr = pop_next

    # Generate time path of the population distribution
    omega_path_lev[:, 0] = pop_curr.copy()
    for per in range(1, T + S):
        pop_next = np.dot(OMEGA_orig, pop_curr)
        omega_path_lev[:, per] = pop_next.copy()
        pop_curr = pop_next.copy()

    # Force the population distribution after 1.5*S periods to be the
    # steady-state distribution by adjusting immigration rates, holding
    # constant mortality, fertility, and SS growth rates
    imm_tol = 1e-14
    fixper = int(1.5 * S)
    omega_SSfx = omega_path_lev[:, fixper] / omega_path_lev[:, fixper].sum()
    imm_objs = (
        fert_rates,
        mort_rates,
        infmort_rate,
        omega_path_lev[:, fixper],
        g_n_SS,
    )
    imm_fulloutput = opt.fsolve(
        immsolve,
        imm_rates_orig,
        args=(imm_objs),
        full_output=True,
        xtol=imm_tol,
    )
    imm_rates_adj = imm_fulloutput[0]
    imm_diagdict = imm_fulloutput[1]
    omega_path_S = omega_path_lev[-S:, :] / np.tile(
        omega_path_lev[-S:, :].sum(axis=0), (S, 1)
    )
    omega_path_S[:, fixper:] = np.tile(
        omega_path_S[:, fixper].reshape((S, 1)), (1, T + S - fixper)
    )
    g_n_path = np.zeros(T + S)
    g_n_path[0] = g_n_curr.copy()
    g_n_path[1:] = (
        omega_path_lev[-S:, 1:].sum(axis=0)
        - omega_path_lev[-S:, :-1].sum(axis=0)
    ) / omega_path_lev[-S:, :-1].sum(axis=0)
    g_n_path[fixper + 1 :] = g_n_SS
    omega_S_preTP = (pop_past.copy()[-S:]) / (pop_past.copy()[-S:].sum())
    imm_rates_mat = np.hstack(
        (
            np.tile(np.reshape(imm_rates_orig[E:], (S, 1)), (1, fixper)),
            np.tile(
                np.reshape(imm_rates_adj[E:], (S, 1)), (1, T + S - fixper)
            ),
        )
    )

    # return omega_path_S, g_n_SS, omega_SSfx, survival rates,
    # mort_rates_S, and g_n_path
    pop_dict = {
        "omega": omega_path_S.T,
        "g_n_SS": g_n_SS,
        "omega_SS": omega_SSfx[-S:] / omega_SSfx[-S:].sum(),
        "surv_rate": 1 - mort_rates_S,
        "rho": mort_rates_S,
        "g_n": g_n_path,
        "imm_rates": imm_rates_mat.T,
        "omega_S_preTP": omega_S_preTP,
    }

    print("pop_dict: ", pop_dict)
    with open("pop_dict_norm.pickle", "wb") as f:
        pickle.dump(pop_dict, f)
        # pickle.dump(pop_dict, f, protocol=pickle.HIGHEST_PROTOCOL)
    pickle.dump(pop_dict, open("pop_dict_5.pickle", "wb"))

    return pop_dict


def exp_b_zerofunc(b, *args):
    """
    This function is the target of the root finder that solves for the exponent
    b in the following functional form:

    .. math::
        &y &= a * (x ** b) + c \quad for x\in[x0, x_N] \\
        \text{such that}\quad &a * x_0^b + c = y0, \\
        \text{and}\quad &a * (x_N ** b) + c = 1 \\
        \text{and}\quad &\sum_{x=x_1}^{x_N} [a x^b + c] = y_{lastbin}

    Args:
        b (scalar): value of b exponent in exponential functional form
        args (4-element tuple): arguments to solve for error function

    Returns:
        error_val (scalar): Error of zero function associated with solution for
            b
    """
    (
        x0,
        xN,
        y0,
        y_lastbin
    ) = args
    if xN > x0:
        distribute_up = True
        step = 1
    elif xN < x0:
        distribute_up = False
        step = -1
    elif xN == x0:
        err_message = ('ERROR exp_b_zerofunc(): xN equals x0.')
        raise ValueError(err_message)
    x1 = x0 + step
    a = (y0 - 1) / ((x0 ** b) - (xN ** b))
    c = 1 - (a * (xN ** b))
    sum_y = 0
    for x in range(x1, xN + step, step):
        sum_y += (a * (x ** b)) + c
    error_val = sum_y - y_lastbin

    return error_val


def distribute_bin(args):
    """
    This function is for distributing aggregated bin data values across
    disaggregated bins according to a monotonically decreasing (or increasing)
    function depending on whether we are distributing bins up (or down). The
    functional form is the following:

    .. math::
        &y &= a * (x ** b) + c \quad for x\in[x0, x_N] \\
        \text{such that}\quad &a * x_0^b + c = y0, \\
        \text{and}\quad &a * (x_N ** b) + c = 1 \\
        \text{and}\quad &\sum_{x=x_1}^{x_N} [a x^b + c] = y_{lastbin}

    Args:
        x0 (int): end x-value to which imputed function must connect
        xN (int): last positive x_value at which imputed function must finish
        xmax (int): for monotonically decreasing (or increasing) function,
            distributing up (down), the maximum (or minimum) value that can
            have a positive value if xN is not high (low) enough
        y0 (scalar): end y-value to which imputed function must connect
        y_lastbin (scalar): total aggregated-bins y-value, to which the sum of
            imputed function values must equal

    Returns:
        x_vec (array_like): array of imputed x-values in ascending order
            (x1,...xN) for distributed-up problem and (xN,...x1) for
            distributed-down problem
        y_vec (array_like): array of imputed y-values in corresponding to x_vec
        abc_vec (array_like): array of estimated values for (a, b, c)
        xN_new (int): updated value for xN
    """
    (
        x0,
        xN,
        xmax,
        y0,
        y_lastbin
    ) = args
    if xN > x0:
        distribute_up = True
        if xmax < xN:
            err_message = ('Error distribute_bin(): xmax < xN for ' +
                           'distribute_up=True.')
            raise ValueError(err_message)
        step = 1
    elif xN < x0:
        distribute_up = False
        if xmax > xN:
            err_message = ('Error distribute_bin(): xmax > xN for ' +
                           'distribute_up=False.')
            raise ValueError(err_message)
        step = -1
    elif xN == x0:
        err_message = ('ERROR distribute_bin(): xN equals x0.')
        raise ValueError(err_message)
    else:
        err_message('ERROR distribute_bin(): xN is neither greater-than, ' +
                    'less-than, or equal to x0 in absolute value.')
        print('xN=', xN, ', x0=', x0, ', xN-x0=', xN - x0)
        raise ValueError(err_message)
    x1 = x0 + step
    # Check if a line a * x + c from x0, y0 to xN, 1 sums up to something
    # greater-than-or-equal to y_lastbin
    lin0 = False
    xN_new = xN
    while not lin0 and step * xN_new <= step * xmax:
        sum_y_lin0 = 0
        a_lin0 = (1 - y0) / (xN_new - x0)
        c_lin0 = 1 - (a_lin0 * xN_new)
        for x in range(x1, xN_new + step, step):
            sum_y_lin0 += (a_lin0 * x) + c_lin0
        lin0 = sum_y_lin0 >= y_lastbin
        print('Sum of lin0 model =', sum_y_lin0, 'for xN=', xN_new)
        print('Sum of lin0 model >=', y_lastbin, '=', lin0)
        if not lin0:
            xN_new += step

    if step * xN_new > step * xN:
        if distribute_up:
            print('NOTE (distribute_bin()): xN value was increased.')
        else:
            print('NOTE (distribute_bin()): xN value was decreased.')

    if step * xN_new > step * xmax:
        xN_new += -step

    if not lin0 and step * xN_new == step * xmax:
        # Distribute final bin as a line from (x0, y0) to xmax and the ymax
        # value that makes the sum equal to y_lastbin
        b = 1.0
        a = ((y_lastbin - (step * (xmax - x0) * y0)) /
             (np.arange(x1, xmax + step, step).sum() -
              (step * (xmax - x0) * x0)))
        c = y0 - a * x0

    elif lin0 and sum_y_lin0 == y_lastbin:
        # If sum_y_lin0 is exactly equal to y_lastbin, set the interpolated y
        # values as a line from (x0, y0) to (xN_new, 1)
        b = 1.0
        a = a_lin0
        c = c_lin0

    elif lin0 and sum_y_lin0 > y_lastbin:
        # Estimate b in three paramter function a * (x ** b) + c
        # such that a * (xN_new ** b) + c = 1,
        # a * (x0 ** b) + c = y0, and
        # sum_{x=x1}^xN_new (a * (x ** b) + c) = y_lastbin
        print('distribute_bin(): Fitting three-parameter function.')
        b_args = (x0, xN_new, y0, y_lastbin)
        b_sol = opt.root(exp_b_zerofunc, x0=1.0, args=b_args)
        b = b_sol.x[0]
        print('b_sol.success=', b_sol.success)
        a = (y0 - 1) / ((x0 ** b) - (xN_new ** b))
        c = 1 - (a * (xN_new ** b))

    if distribute_up:
        x_vec = np.arange(x1, xN_new + 1)
    else:
        x_vec = np.arange(xN_new, x1 + 1)
    y_vec = (a * (x_vec ** b)) + c
    abc_vec = np.array([a, b, c])

    return x_vec, y_vec, abc_vec, xN_new
