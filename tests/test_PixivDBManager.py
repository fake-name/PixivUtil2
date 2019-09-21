#!/c/Python27/python.exe
# -*- coding: UTF-8 -*-


from pixivutil2.PixivDBManager import PixivDBManager
from pixivutil2.PixivModel import PixivListItem
from pixivutil2.PixivConfig import PixivConfig

import unittest
LIST_SIZE = 9
config = PixivConfig()
config.loadConfig()


class TestPixivDBManager(unittest.TestCase):
    def testImportListTxt(self):
        DB = PixivDBManager(target="./tests/test_files/test.db.sqlite")
        DB.createDatabase()
        l = PixivListItem.parseList("./tests/test_files/test.list.txt", config.rootDirectory)
        result = DB.importList(l)
        self.assertEqual(result, 0)

    def testSelectMembersByLastDownloadDate(self):
        DB = PixivDBManager(target="./tests/test_files/test.db.sqlite")
        DB.createDatabase()
        l = PixivListItem.parseList("./tests/test_files/test.list.txt", config.rootDirectory)
        result = DB.selectMembersByLastDownloadDate(7)
        self.assertEqual(len(result), LIST_SIZE)
        for item in result:
            print(item.memberId, item.path)

    def testSelectAllMember(self):
        DB = PixivDBManager(target="./tests/test_files/test.db.sqlite")
        DB.createDatabase()
        l = PixivListItem.parseList("./tests/test_files/test.list.txt", config.rootDirectory)
        result = DB.selectAllMember()
        self.assertEqual(len(result), LIST_SIZE)
        for item in result:
            print(item.memberId, item.path)


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPixivDBManager)
    unittest.TextTestRunner(verbosity=5).run(suite)
    print("================================================================")
