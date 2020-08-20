import os
import sys
import pandas as pd
sys.path.append('src')
from FileOps import FileReader, FileWriter  # noqa autopep8

dir_path = os.path.dirname(os.path.realpath(__file__))
json_path1 = os.path.join(dir_path, 'test1.json')
json_path2 = os.path.join(dir_path, 'test2.json')

empty = {}
data = [
    {
        'symbol': 'AMZN',
        'open': 2400.85,
        'volume': 402265,
        'date': '2020-12-25'
    },
    {
        'symbol': 'AAPL',
        'open': 300.90,
        'volume': 502265,
        'date': '2015-01-15'
    }
]
snippet = {
    'symbol': 'NVDA',
    'open': 445.00,
    'volume': 102265,
    'date': '2015-01-15'
}
data_ = data[:]
data_.append(snippet)

csv_path1 = os.path.join(dir_path, 'test1.csv')
csv_path2 = os.path.join(dir_path, 'test2.csv')
test_df = pd.DataFrame(data)
big_df = pd.DataFrame(data_)
small_df = pd.DataFrame([snippet])
empty_df = pd.DataFrame()

reader = FileReader()
writer = FileWriter()


class TestFileWriter:
    def test_init(self):
        assert type(writer).__name__ == 'FileWriter'

    def test_save_json(self):
        # save empty json object
        writer.save_json(json_path1, {})
        assert os.path.exists(json_path1)

        # save list of 2 json objects
        writer.save_json(json_path2, data)
        assert os.path.exists(json_path2)

    def test_save_csv(self):
        # save empty table
        writer.save_csv(csv_path1, empty_df)
        assert os.path.exists(csv_path1)

        # save table with 2 rows
        writer.save_csv(csv_path2, test_df)
        assert os.path.exists(csv_path2)

    def test_update_csv(self):
        writer.update_csv(csv_path2, test_df)
        assert reader.load_csv(csv_path2).equals(test_df)

        writer.update_csv(csv_path2, small_df)
        assert reader.load_csv(csv_path2).equals(test_df)
        assert not reader.load_csv(csv_path2).equals(small_df)

        writer.update_csv(csv_path2, big_df)
        assert reader.load_csv(csv_path2).equals(big_df)
        assert not reader.load_csv(csv_path2).equals(test_df)

        writer.save_csv(csv_path2, test_df)


class TestFileReader:
    def test_init(self):
        assert type(reader).__name__ == 'FileReader'

    def test_load_json(self):
        # empty case from above
        assert reader.load_json(json_path1) == empty
        # mock data case from above
        assert reader.load_json(json_path2) == data

        os.remove(json_path1)
        os.remove(json_path2)

    def test_load_csv(self):
        # empty case from above
        assert reader.load_csv(csv_path1).equals(empty_df)
        # mock data case from above
        assert reader.load_csv(csv_path2).equals(test_df)

    def test_check_update(self):
        assert reader.check_update(csv_path2, test_df) is True
        assert reader.check_update(csv_path2, small_df) is False
        assert reader.check_update(csv_path2, big_df) is True

    def test_update_df(self):
        assert reader.update_df(csv_path2, test_df, 'date').equals(test_df)
        assert reader.update_df(csv_path2, big_df, 'date').equals(big_df)
