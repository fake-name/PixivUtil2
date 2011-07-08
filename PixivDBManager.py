#!/usr/bin/python
# -*- coding: UTF-8 -*-

import sqlite3

import sys
import os
import traceback
import logging

import codecs

class PixivDBManager:
    """Pixiv Database Manager"""
    
    def __init__(self):
        self.conn = sqlite3.connect('db.sqlite')

    def close(self):
        self.conn.close()

##########################################
## I. Create/Drop Database              ##
##########################################
    def createDatabase(self):
        print 'Creating database...',
        
        try:
            c = self.conn.cursor()

            c.execute('''CREATE TABLE IF NOT EXISTS pixiv_master_member (
                            member_id INTEGER PRIMARY KEY ON CONFLICT IGNORE,
                            name TEXT,
                            save_folder TEXT,
                            created_date DATE,
                            last_update_date DATE,
                            last_image INTEGER
                            )''')
            
            self.conn.commit()

            c.execute('''CREATE TABLE IF NOT EXISTS pixiv_master_image (
                            image_id INTEGER PRIMARY KEY,
                            member_id INTEGER,
                            title TEXT,
                            save_name TEXT,
                            created_date DATE,
                            last_update_date DATE
                            )''')
            self.conn.commit()
            
            print 'done.'
        except:
            print 'Error at createDatabase():',str(sys.exc_info())
            print 'failed.'
            raise
        finally:
            c.close()

    def dropDatabase(self):
        try:
            c = self.conn.cursor()
            c.execute('''DROP IF EXISTS TABLE pixiv_master_member''')
            self.conn.commit()

            c.execute('''DROP IF EXISTS TABLE pixiv_master_image''')
            self.conn.commit()
        except:
            print 'Error at dropDatabase():',str(sys.exc_info())
            print 'failed.'
            raise
        finally:
            c.close()
        print 'done.'

##########################################
## II. Export/Import DB                 ##
##########################################                    
    def importList(self,filename):
        print 'Importing list...',
        try:
            c = self.conn.cursor()
            reader = open(filename,'r')
            for line in reader:
                if line.startswith('#'):
                    continue
                member_id = int(line)
                c.execute('''INSERT OR IGNORE INTO pixiv_master_member VALUES(?, ?, ?, datetime('now'), '1-1-1', -1)''',
                                  (member_id, str(member_id), 'N\A'))
            self.conn.commit()
        except:
            print 'Error at importList():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
        print 'done.'

    def exportList(self,filename):
        print 'Exporting list...',
        try:
            c = self.conn.cursor()
            c.execute('''SELECT member_id FROM pixiv_master_member
                            ORDER BY member_id''')
            filename = filename + '.txt'
            writer = open(filename, 'w')            
            for row in c:
                for string in row:
                    writer.write(str(string))
                writer.write('\n')
            writer.write('###END-OF-FILE###')
            writer.close()
        except:
            print 'Error at exportList():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
        print 'done.'

    def exportDetailedList(self, filename):
        print 'Exporting detailed list...',
        try:
            c = self.conn.cursor()
            c.execute('''SELECT * FROM pixiv_master_member
                            ORDER BY member_id''')
            filename = filename + '.csv'
            writer = codecs.open(filename, 'wb', encoding='utf-8')
            writer.write('member_id,name,save_folder,created_date,last_update_date,last_image\r\n')
            for row in c:
                for string in row:
                    #try:
                        ### TODO: Unicode write!!
                        #print unicode(string)
                        data = unicode(string)
                        writer.write(data)
                        writer.write(',')
                    #except:
                    #    print 'exception: write'
                    #    writer.write(u',')
                writer.write('\r\n')
            writer.write('###END-OF-FILE###')
            writer.close()
        except:
            print 'Error at exportDetailedList(): ' + str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
        print 'done.'

##########################################
## III. Print DB                        ##
##########################################          
    def printMemberList(self):
        print 'Printing member list:'
        try:
            c = self.conn.cursor()
            c.execute('''SELECT * FROM pixiv_master_member
                            ORDER BY member_id''')
            print 'member_id\tname\tsave_folder\tcreated_date\tlast_update_date\tlast_image'
            i = 0
            for row in c:
                for string in row:
                    print '\t',
                    self.safePrint(string)
                print ''
                i = i + 1
                if i == 79:
                    select = raw_input('Continue [y/n]? ')
                    if select == 'n':
                        break
                    else :
                        print 'member_id\tname\tsave_folder\tcreated_date\tlast_update_date\tlast_image'
                        i = 0
        except:
            print 'Error at printList():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
        print 'done.'
        
    def printImageList(self):
        print 'Printing image list:'
        try:
            c = self.conn.cursor()
            c.execute(''' SELECT COUNT(*) FROM pixiv_master_image''')
            result = c.fetchall()
            if result[0][0] > 10000:
                print 'Row count is more than 10000 (actual row count:',str(result[0][0]),')'
                print 'It may take a while to retrieve the data.'
                answer = raw_input('Continue [y/n]')
                if answer == 'y':
                    c.execute('''SELECT * FROM pixiv_master_image
                                    ORDER BY member_id''')
                    print ''
                    for row in c:
                        for string in row:
                            print '   ',
                            self.safePrint(string)
                        print ''
                else :
                    return
            #Yavos: it seems you forgot something ;P
            else:
                c.execute('''SELECT * FROM pixiv_master_image
                                    ORDER BY member_id''')
                print ''
                for row in c:
                    for string in row:
                        print '   ',
                        self.safePrint(string) #would it make more sense to set output to file?
                    print ''    
            #Yavos: end of change
        except:
            print 'Error at printImageList():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
        print 'done.'

##########################################
## IV. CRUD Member Table                ##
##########################################
    def insertNewMember(self):
        try:
            c = self.conn.cursor()
            member_id = 0
            while True:
                temp = raw_input('Member ID: ')
                try:
                    member_id = int(temp)
                except:
                    pass
                if member_id > 0:
                    break
            
            c.execute('''INSERT OR IGNORE INTO pixiv_master_member VALUES(?, ?, ?, datetime('now'), '1-1-1', -1)''',
                                  (member_id, str(member_id), 'N\A'))
        except:
            print 'Error at insertNewMember():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
            
    def selectAllMember(self):
        try:
            c = self.conn.cursor()
            c.execute('''SELECT member_id FROM pixiv_master_member ORDER BY member_id''')
            result = c.fetchall()
        except:
            print 'Error at selectAllMember():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
            
        return result

    def selectMembersByLastDownloadDate(self, difference):
        try:
            c = self.conn.cursor()
            try:
                int_diff = int(difference)
            except ValueError:
                int_diff = 7
                
            c.execute('''SELECT member_id, (julianday(Date('now')) - julianday(last_update_date)) as diff FROM pixiv_master_member WHERE last_image == -1 OR diff > '''+ str(int_diff) +''' ORDER BY member_id''')
            result = c.fetchall()
        except:
            print 'Error at selectAllMember():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
            
        return result
    
    def selectMemberByMemberId(self, member_id):
        try:
            c = self.conn.cursor()
            c.execute('''SELECT * FROM pixiv_master_member WHERE member_id = ? ''', (member_id, ))
            return c.fetchone()
        except:
            print 'Error at selectMemberByMemberId():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
            
    def printMembersByLastDownloadDate(self, difference):
        rows = self.selectMembersByLastDownloadDate(difference)

        for row in rows:
            for string in row:
                print '   ',
                self.safePrint(string)
            print '\n'
    
    def updateMemberName(self, memberId, memberName):
        try:
            c = self.conn.cursor()
            c.execute('''UPDATE pixiv_master_member
                            SET name = ?
                            WHERE member_id = ?
                            ''', (memberName, memberId))
            self.conn.commit()
        except:
            print 'Error at updateMemberId():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
            
    def updateSaveFolder(self, memberId, saveFolder):
        try:
            c = self.conn.cursor()
            c.execute('''UPDATE pixiv_master_member
                            SET save_folder = ?
                            WHERE member_id = ?
                            ''', (saveFolder, memberId))
            self.conn.commit()
        except:
            print 'Error at updateSaveFolder():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()

    def updateLastDownloadedImage(self, memberId, imageId):
        try:
            c = self.conn.cursor()
            c.execute('''UPDATE pixiv_master_member
                            SET last_image = ?, last_update_date = datetime('now')
                            WHERE member_id = ?''',
                            (imageId, memberId))
            self.conn.commit()
        except:
            print 'Error at updateMemberId():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()

    def deleteMemberByMemberId(self, memberId):
        try:
            c = self.conn.cursor()
            c.execute('''DELETE FROM pixiv_master_member
                            WHERE member_id = ?''',
                            (memberId, ))
            self.conn.commit()
        except:
            print 'Error at deleteMemberByMemberId():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
            
    def deleteCascadeMemberByMemberId(self, memberId):
        try:
            c = self.conn.cursor()
            c.execute('''DELETE FROM pixiv_master_image
                            WHERE member_id = ?''',
                            (memberId, ))
            c.execute('''DELETE FROM pixiv_master_member
                            WHERE member_id = ?''',
                            (memberId, ))
            self.conn.commit()
        except:
            print 'Error at deleteCascadeMemberByMemberId():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()

##########################################
## V. CRUD Image Table                  ##
##########################################
    def insertImage(self, memberId,ImageId):
        try:
            c = self.conn.cursor()
            memberId = int(memberId)
            ImageId = int(ImageId)
            c.execute('''INSERT OR IGNORE INTO pixiv_master_image VALUES(?, ?, 'N/A' ,'N/A' , datetime('now'), datetime('now') )''',
                              (ImageId, memberId))
            self.conn.commit()
        except:
            print 'Error at insertImage():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()

    def blacklistImage(self, memberId,ImageId):
        try:
            c = self.conn.cursor()
            c.execute('''INSERT OR REPLACE INTO pixiv_master_image VALUES(?, ?, '**BLACKLISTED**' ,'**BLACKLISTED**' , datetime('now'), datetime('now') )''',
                              (ImageId, memberId))
            self.conn.commit()
        except:
            print 'Error at insertImage():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
        
    def selectImageByMemberId(self, memberId):
        try:
            c = self.conn.cursor()
            c.execute('''SELECT * FROM pixiv_master_image WHERE member_id = ? ''', (memberId, ))
            return c.fetchall()
        except:
            print 'Error at selectImageByImageId():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()
        
    def selectImageByMemberIdAndImageId(self, memberId, imageId):
        try:
            c = self.conn.cursor()
            c.execute('''SELECT image_id FROM pixiv_master_image WHERE image_id = ? AND save_name != 'N/A' AND member_id = ?''', (imageId, memberId))
            return c.fetchone()
        except:
            print 'Error at selectImageByImageId():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()

    def selectImageByImageId(self,imageId):
        try:
            c = self.conn.cursor()
            c.execute('''SELECT * FROM pixiv_master_image WHERE image_id = ? AND save_name != 'N/A' ''', (imageId, ))
            return c.fetchone()
        except:
            print 'Error at selectImageByImageId():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()

    def updateImage(self, imageId, title, filename):
        try:
            c = self.conn.cursor()
            c.execute('''UPDATE pixiv_master_image
                        SET title = ?, save_name = ?, last_update_date = datetime('now')
                        WHERE image_id = ?''',
                        (title, filename, imageId))
            self.conn.commit()
        except:
            print 'Error at updateImage():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()

    def deleteImage(self, imageId):
        try:
            c = self.conn.cursor()
            c.execute('''DELETE FROM pixiv_master_image
                        WHERE image_id = ?''',
                        (imageId, ))
            self.conn.commit()
        except:
            print 'Error at deleteImage():',str(sys.exc_info())
            print 'failed'
            raise
        finally:
            c.close()

##########################################
## VI. Utilities                        ##
##########################################
    def safePrint(self,msg):
        try:
            print msg,
        except UnicodeError:
            print '',
        return ' '
    def getInt(self, inputStr):
        inputInt = None
        while True:
            try:
                inputInt = int(inputStr)
            except:
                pass
            if inputInt != None:
                return inputInt
            
            
    def menu(self):
        print 'Pixiv DB Manager Console'
        print '1. Show all member'
        print '2. Show all images'
        print '3. Export list (member_id only)'
        print '4. Export list (detailed)'
        print '5. Show member by last downloaded date'
        print '6. Show image by image_id'
        print '7. Show member by member_id'
        print '8. Show image by member_id'
        print '9. Delete member by member_id'
        print '10. Delete image by image_id'
        print '11. Delete member and image (cascade deletion)'
        print '12. Blacklist image by image_id'
        
        print 'x. Exit'
        selection = raw_input('Select one?')
        return selection

    def main(self):
        try:
            while True:
                selection = self.menu()

                if selection == '1':
                    self.printMemberList()
                if selection == '2':
                    self.printImageList()
                if selection == '3':
                    filename = raw_input('Filename? ')
                    self.exportList(filename)
                if selection == '4':
                    filename = raw_input('Filename? ')
                    self.exportDetailedList(filename)
                if selection == '5':
                    date = raw_input('Number of date? ')
                    rows = self.selectMembersByLastDownloadDate(date)
                    if rows != None:
                        for row in rows:
                            for string in row:
                                print '\t\t',
                                self.safePrint(string)
                            print '\n'
                    else :
                        print 'Not Found!\n'
                if selection == '6':
                    image_id = raw_input('image_id? ')
                    row = self.selectImageByImageId(image_id)
                    if row != None:
                        for string in row:
                            print '\t\t',
                            self.safePrint(string)
                        print '\n'
                    else :
                        print 'Not Found!\n'
                if selection == '7':
                    member_id = raw_input('member_id? ')
                    row = self.selectMemberByMemberId(member_id)
                    if row != None:
                        for string in row:
                            print '\t\t',
                            self.safePrint(string)
                        print '\n'
                    else :
                        print 'Not Found!\n'
                if selection == '8':
                    member_id = raw_input('member_id? ')
                    rows = self.selectImageByMemberId(member_id)
                    if rows != None:
                        for row in rows:
                            for string in row:
                                print '\t\t',
                                self.safePrint(string)
                            print '\n'
                    else :
                        print 'Not Found!\n'
                if selection == '9':
                    member_id = raw_input('member_id? ')
                    self.deleteMemberByMemberId(member_id)
                if selection == '10':
                    image_id = raw_input('image_id? ')
                    self.deleteImage(image_id)
                if selection == '11':
                    member_id = raw_input('member_id? ')
                    self.deleteCascadeMemberByMemberId(member_id)
                if selection == '12':
                    member_id = raw_input('member_id? ')
                    image_id = raw_input('image_id? ')
                    self.blacklistImage(member_id, image_id)
                    
                if selection == 'x':
                    break
            print 'end PixivDBManager.'
        except:
            print 'Error: ', sys.exc_info()
            ##raw_input('Press enter to exit.')
            self.main()
    
if __name__ == '__main__':
    apps = PixivDBManager()
    apps.main()