#/***************************************************************************
# *   Copyright (c) Victor Titov (DeepSOIC)                                 *
# *                                           (vv.titov@gmail.com) 2016     *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This library is free software; you can redistribute it and/or         *
# *   modify it under the terms of the GNU Library General Public           *
# *   License as published by the Free Software Foundation; either          *
# *   version 2 of the License, or (at your option) any later version.      *
# *                                                                         *
# *   This library  is distributed in the hope that it will be useful,      *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this library; see the file COPYING.LIB. If not,    *
# *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
# *   Suite 330, Boston, MA  02111-1307, USA                                *
# *                                                                         *
# ***************************************************************************/

from __future__ import absolute_import 

import FreeCAD as App
import Part
from FreeCAD import Units
from Units import MilliMetre as mm
from Units import Degree as deg
from Units import Quantity as Q

from AttachmentEditor.FrozenClass import FrozenClass
from AttachmentEditor.TempoVis import TempoVis
from AttachmentEditor.DepGraphTools import getAllDependent

if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui
    from FreeCADGui import PySideUic as uic

#-------------------------- translation-related code ----------------------------------------
#Thanks, yorik! (see forum thread "A new Part tool is being born... JoinFeatures!"
#http://forum.freecadweb.org/viewtopic.php?f=22&t=11112&start=30#p90239 )
try:
    _fromUtf8 = QtCore.QString.fromUtf8
except AttributeError:
    def _fromUtf8(s):
        return s
try:
    _encoding = QtGui.QApplication.UnicodeUTF8
    def _translate(context, text, disambig):
        return QtGui.QApplication.translate(context, text, disambig, _encoding)
except AttributeError:
    def _translate(context, text, disambig):
        return QtGui.QApplication.translate(context, text, disambig)
#--------------------------/translation-related code ----------------------------------------


def StrFromLink(feature, subname):
    return feature.Name+ ((':'+subname) if subname else '')
    
def LinkFromStr(strlink, document):
    if len(strlink) == 0:
        return None
    pieces = strlink.split(':')
    
    feature = document.getObject(pieces[0])
    
    subname = ''
    if feature is None:
        raise ValueError(_translate('AttachmentEditor',"No object named {name}",None).format(name= pieces[0]))
    if len(pieces) == 2:
        subname = pieces[1]
    elif len(pieces) > 2:
        raise ValueError(_translate('AttachmentEditor',"Failed to parse link (more than one colon encountered)",None))
    
    return (feature,str(subname)) #wrap in str to remove unicode, which confuses assignment to PropertyLinkSubList.

def StrListFromRefs(references):
    '''input: PropertyLinkSubList. Output: list of strings for UI.'''
    return [StrFromLink(feature,subelement) for (feature, subelement) in references]

def RefsFromStrList(strings, document):
    '''input: strings as from UI. Output: list of tuples that can be assigned to PropertyLinkSubList.'''
    refs = []
    for st in strings:
        lnk = LinkFromStr(st, document)
        if lnk is not None:
            refs.append(lnk)
    return refs

def GetSelectionAsLinkSubList():
    sel = Gui.Selection.getSelectionEx()
    result = []
    for selobj in sel:
        for subname in selobj.SubElementNames:
            result.append((selobj, subname))
        if len(selobj.SubElementNames) == 0:
            result.append((selobj, ''))
    return result

def PlacementsFuzzyCompare(plm1, plm2):
    pos_eq = (plm1.Base - plm2.Base).Length < 1e-7   # 1e-7 is OCC's Precision::Confusion
    
    q1 = plm1.Rotation.Q
    q2 = plm2.Rotation.Q
    # rotations are equal if q1 == q2 or q1 == -q2. 
    # Invert one of Q's if their scalar product is negative, before comparison.
    if q1[0]*q2[0] + q1[1]*q2[1] + q1[2]*q2[2] + q1[3]*q2[3] < 0:
        q2 = [-v for v in q2]
    rot_eq = (  abs(q1[0]-q2[0]) + 
                abs(q1[1]-q2[1]) + 
                abs(q1[2]-q2[2]) + 
                abs(q1[3]-q2[3])  ) < 1e-12   # 1e-12 is OCC's Precision::Angular (in radians)
    return pos_eq and rot_eq

class CancelError(Exception):
    def __init__(self):
        self.message = 'Canceled by user'
        self.isCancelError = True
        
class AttachmentEditorTaskPanel(FrozenClass):
    '''The editmode TaskPanel for attachment editing'''
    KEYmode = QtCore.Qt.ItemDataRole.UserRole # Key to use in Item.data(key) to obtain a mode associated with list item
    KEYon = QtCore.Qt.ItemDataRole.UserRole + 1 # Key to use in Item.data(key) to obtain if the mode is valid
    
    def __define_attributes(self):
        self.obj = None #feature being attached
        self.attacher = None #AttachEngine that is being actively used by the dialog. Its parameters are constantly and actively kept in sync with the dialog.
        self.obj_is_attachable = True # False when editing non-attachable objects (alignment, not attachment)

        self.last_sugr = None #result of last execution of suggestor

        self.form = None #Qt widget of dialog interface
        self.block = False #when True, event handlers return without doing anything (instead of doing-undoing blockSignals to everything)
        self.refLines = [] #reference lineEdit widgets, packed into a list for convenience
        self.refButtons = [] #buttons next to reference lineEdits
        self.superPlacementEdits = [] #all edit boxes related to superplacement
        self.i_active_ref = -1 #index of reference being selected (-1 means no reaction to selecting)
        self.auto_next = False #if true, references being selected are appended ('Selecting' state is automatically advanced to next button)
        
        self.tv = None #TempoVis class instance
        
        self.create_transaction = True # if false, dialog doesn't mess with transactions.
        self.callback_OK        = None
        self.callback_Cancel    = None 
        self.callback_Apply     = None 

        self._freeze()
    
    def __init__(self, obj_to_attach,
                       take_selection = False, 
                       create_transaction = True,
                       callback_OK        = None, 
                       callback_Cancel    = None,
                       callback_Apply     = None):
        
        self.__define_attributes()
        
        self.create_transaction = create_transaction
        self.callback_OK        = callback_OK       
        self.callback_Cancel    = callback_Cancel   
        self.callback_Apply     = callback_Apply    
        
        self.obj = obj_to_attach
        if hasattr(obj_to_attach,'Attacher'):
            self.attacher = obj_to_attach.Attacher
        elif hasattr(obj_to_attach,'AttacherType'):
            self.attacher = Part.AttachEngine(obj_to_attach.AttacherType)
        else:
            movable = True
            if not hasattr(self.obj, "Placement"):
                movable = False
            if 'Hidden' in self.obj.getEditorMode("Placement") or 'ReadOnly' in self.obj.getEditorMode("Placement"):
                movable = False
            if not movable:
                if self.callback_Cancel:
                    self.callback_Cancel()
                raise ValueError(_translate('AttachmentEditor',"Object {name} is neither movable nor attachable, can't edit attachment",None)
                                 .format(name= self.obj.Label))
                
            self.obj_is_attachable = False
            self.attacher = Part.AttachEngine()
            
            mb = QtGui.QMessageBox()
            mb.setIcon(mb.Icon.Warning)
            mb.setText(_translate('AttachmentEditor',
                         "{obj} is not attachable. You can still use attachment editor dialog to align the object, but the attachment won't be parametic."
                         ,None)
                       .format(obj= obj_to_attach.Label))
            mb.setWindowTitle(_translate('AttachmentEditor',"Attachment",None))
            btnAbort = mb.addButton(QtGui.QMessageBox.StandardButton.Abort)
            btnOK = mb.addButton(_translate('AttachmentEditor',"Continue",None),QtGui.QMessageBox.ButtonRole.ActionRole)
            mb.setDefaultButton(btnOK)
            mb.exec_()
            if mb.clickedButton() is btnAbort:
                if self.callback_Cancel:
                    self.callback_Cancel()
                raise CancelError()
        
        import os
        self.form=uic.loadUi(os.path.dirname(__file__) + os.path.sep + 'TaskAttachmentEditor.ui')
        # self.form.setWindowIcon(QtGui.QIcon(':/icons/PartDesign_InternalExternalGear.svg'))
        self.form.setWindowTitle(_translate('AttachmentEditor',"Attachment",None))
        
        self.refLines = [self.form.lineRef1, 
                         self.form.lineRef2,
                         self.form.lineRef3,
                         self.form.lineRef4]
        self.refButtons = [self.form.buttonRef1,
                           self.form.buttonRef2,
                           self.form.buttonRef3,
                           self.form.buttonRef4]
        self.superPlacementEdits = [self.form.superplacementX,
                                    self.form.superplacementY,
                                    self.form.superplacementZ,
                                    self.form.superplacementYaw,
                                    self.form.superplacementPitch,
                                    self.form.superplacementRoll]
                           
        self.block = False
                           
        for i in range(len(self.refLines)):
            QtCore.QObject.connect(self.refLines[i], QtCore.SIGNAL('textEdited(QString)'), lambda txt, i=i: self.lineRefChanged(i,txt))

        for i in range(len(self.refLines)):
            QtCore.QObject.connect(self.refButtons[i], QtCore.SIGNAL('clicked()'), lambda i=i: self.refButtonClicked(i))
        
        for i in range(len(self.superPlacementEdits)):
            QtCore.QObject.connect(self.superPlacementEdits[i], QtCore.SIGNAL('valueChanged(double)'), lambda val, i=i: self.superplacementChanged(i,val))
            
        QtCore.QObject.connect(self.form.checkBoxFlip, QtCore.SIGNAL('clicked()'), self.checkBoxFlipClicked)
        
        QtCore.QObject.connect(self.form.listOfModes, QtCore.SIGNAL('itemSelectionChanged()'), self.modeSelected)
        
        if self.create_transaction:
            self.obj.Document.openTransaction(_translate('AttachmentEditor',"Edit attachment of {feat}",None).format(feat= self.obj.Name))
        

        self.readParameters()

        
        if len(self.attacher.References) == 0 and take_selection:
            sel = GetSelectionAsLinkSubList()
            for i in range(len(sel))[::-1]:
                if sel[i][0] is obj_to_attach:
                    sel.pop(i)
            self.attacher.References = sel
        if len(self.attacher.References) == 0:
            self.i_active_ref = 0
            self.auto_next = True
        else:
            self.i_active_ref = -1
            self.auto_next = False

        Gui.Selection.addObserver(self)

        self.updatePreview()
        self.updateRefButtons()
        
        self.tv = TempoVis(self.obj.Document)
        self.tv.hide_all_dependent(self.obj)
        self.tv.show(self.obj)
        self.tv.show([obj for (obj,subname) in self.attacher.References])
    
    # task dialog handling
    def getStandardButtons(self):
        return int(QtGui.QDialogButtonBox.Ok) | int(QtGui.QDialogButtonBox.Cancel)| int(QtGui.QDialogButtonBox.Apply)
    
    def clicked(self,button):
        if button == QtGui.QDialogButtonBox.Apply:
            if self.obj_is_attachable:
                self.writeParameters()
            self.updatePreview()
            if self.callback_Apply:
                self.callback_Apply()

    def accept(self):
        if self.obj_is_attachable:
            self.writeParameters()
        if self.create_transaction:
            self.obj.Document.commitTransaction()
        self.cleanUp()
        Gui.Control.closeDialog()
        if self.callback_OK:
            self.callback_OK()
        
    def reject(self):
        if self.create_transaction:
            self.obj.Document.abortTransaction()
        self.cleanUp()
        Gui.Control.closeDialog()
        if self.callback_Cancel:
            self.callback_Cancel()


    #selectionObserver stuff
    def addSelection(self,docname,objname,subname,pnt):
        i = self.i_active_ref
        if i < 0:
            #not selecting any reference
            return
        if i > 0 and self.auto_next:
            prevref = LinkFromStr( self.refLines[i-1].text(), self.obj.Document )
            if prevref[0].Name == objname and subname == '':
                # whole object was selected by double-clicking
                # its subelement was already written to line[i-1], so we decrease i to overwrite the lineRefChanged
                i -= 1
        if i > len(self.refLines)-1:
            # all 4 references have been selected, finish
            assert(self.auto_next)
            self.i_active_ref = -1
            self.updateRefButtons()
            return
        if i > -1:
            # assign the selected reference
            if objname == self.obj.Name:
                self.form.message.setText(_translate('AttachmentEditor',"Ignored. Can't attach object to itself!",None))
                return
            if App.getDocument(docname).getObject(objname) in getAllDependent(self.obj):
                self.form.message.setText(_translate('AttachmentEditor',"{obj1} depends on object being attached, can't use it for attachment",None).format(obj1= objname))
                return

            self.refLines[i].setText( StrFromLink(App.getDocument(docname).getObject(objname), subname) )
            self.lineRefChanged(i,'')
            if self.auto_next:
                i += 1
        self.i_active_ref = i
        self.updateRefButtons()
    
    # slots

    def superplacementChanged(self, index, value):
        if self.block:
            return
        plm = self.attacher.SuperPlacement
        pos = plm.Base
        if index==0:
            pos.x = Q(self.form.superplacementX.text()).getValueAs(mm)
        if index==1:
            pos.y = Q(self.form.superplacementY.text()).getValueAs(mm)
        if index==2:
            pos.z = Q(self.form.superplacementZ.text()).getValueAs(mm)
        if index >= 0  and  index <= 2:
            plm.Base = pos

        rot = plm.Rotation;
        (yaw, pitch, roll) = rot.toEuler()
        if index==3:
            yaw = Q(self.form.superplacementYaw.text()).getValueAs(deg)
        if index==4:
            pitch = Q(self.form.superplacementPitch.text()).getValueAs(deg)
        if index==5:
            roll = Q(self.form.superplacementRoll.text()).getValueAs(deg)
        if index >= 3  and  index <= 5:
            rot = App.Rotation(yaw,pitch,roll)
            plm.Rotation = rot
        
        self.attacher.SuperPlacement = plm
        
        self.updatePreview()

    def checkBoxFlipClicked(self):
        if self.block:
            return
        self.attacher.Reverse = self.form.checkBoxFlip.isChecked()
        self.updatePreview()

    def lineRefChanged(self, index, value):
        if self.block:
            return
        # not parsing links here, because doing it in updatePreview will display error message
        self.updatePreview()

    def refButtonClicked(self, index):
        if self.block:
            return
        if self.i_active_ref == index:
            #stop selecting
            self.i_active_ref = -1
        else:
            #start selecting
            self.i_active_ref = index
            self.auto_next = False
        self.updateRefButtons()
    
    def modeSelected(self):
        if self.block: 
            return
        self.attacher.Mode = self.getCurrentMode()        
        self.updatePreview()
        
    #internal methods
    def writeParameters(self):
        'Transfer from the dialog to the object' 
        self.attacher.writeParametersToFeature(self.obj)
        
    def readParameters(self):
        'Transfer from the object to the dialog'
        if self.obj_is_attachable:
            self.attacher.readParametersFromFeature(self.obj)
        
        plm = self.attacher.SuperPlacement
        try:
            old_selfblock = self.block 
            self.block = True
            self.form.superplacementX.setText    ((plm.Base.x * mm).UserString)
            self.form.superplacementY.setText    ((plm.Base.y * mm).UserString)
            self.form.superplacementZ.setText    ((plm.Base.z * mm).UserString)
            self.form.superplacementYaw.setText  ((plm.Rotation.toEuler()[0] * deg).UserString)
            self.form.superplacementPitch.setText((plm.Rotation.toEuler()[1] * deg).UserString)
            self.form.superplacementRoll.setText ((plm.Rotation.toEuler()[2] * deg).UserString)
            
            self.form.checkBoxFlip.setChecked(self.attacher.Reverse)
            
            strings = StrListFromRefs(self.attacher.References)
            if len(strings) < len(self.refLines):
                strings.extend(['']*(len(self.refLines) - len(strings)))
            for i in range(len(self.refLines)):
                self.refLines[i].setText(strings[i])
        finally:
            self.block = old_selfblock
        
    def parseAllRefLines(self):
        self.attacher.References = RefsFromStrList([le.text() for le in self.refLines], self.obj.Document)
    
    def updateListOfModes(self):
        '''needs suggestor to have been called, and assigned to self.last_sugr'''
        try:
            old_selfblock = self.block 
            self.block = True
            list_widget = self.form.listOfModes
            list_widget.clear()
            sugr = self.last_sugr
            # add valid modes
            for m in sugr['allApplicableModes']:
                item = QtGui.QListWidgetItem()
                txt = self.attacher.getModeInfo(m)['UserFriendlyName']
                item.setText(txt)
                item.setData(self.KEYmode,m)
                item.setData(self.KEYon,True)
                if m == sugr['bestFitMode']:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                list_widget.addItem(item)
                item.setSelected(self.attacher.Mode == m)
            # add potential modes
            for m in sugr['reachableModes'].keys():
                item = QtGui.QListWidgetItem()
                txt = self.attacher.getModeInfo(m)['UserFriendlyName']
                listlistrefs = sugr['reachableModes'][m]
                if len(listlistrefs) == 1:
                    listrefs_userfriendly = [self.attacher.getRefTypeInfo(t)['UserFriendlyName'] for t in listlistrefs[0]]
                    txt = _translate('AttachmentEditor',"{mode} (add {morerefs})",None).format(mode= txt, 
                                                           morerefs= u"+".join(listrefs_userfriendly))
                else:
                    txt = _translate('AttachmentEditor',"{mode} (add more references)",None).format(mode= txt)
                item.setText(txt)
                item.setData(self.KEYmode,m)
                item.setData(self.KEYon,True)
                if m == sugr['bestFitMode']:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                
                #disable this item
                f = item.flags()
                f = f & ~(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable)
                item.setFlags(f)
                
                list_widget.addItem(item)
            
            # re-scan the list to fill in tooltips
            for item in list_widget.findItems('', QtCore.Qt.MatchContains):
                m = item.data(self.KEYmode)
                on = item.data(self.KEYon)

                mi = self.attacher.getModeInfo(m)
                cmb = []
                for refstr in mi['ReferenceCombinations']:
                    refstr_userfriendly = [self.attacher.getRefTypeInfo(t)['UserFriendlyName'] for t in refstr]
                    cmb.append(u", ".join(refstr_userfriendly))
                tip = _translate('AttachmentEditor',"{docu}\n\nReference combinations:\n{combinations}",None).format(docu=mi['BriefDocu'], combinations= u"\n".join(cmb) )

                item.setToolTip(tip)

        finally:
            self.block = old_selfblock

    
    def updateRefButtons(self):
        try:
            old_selfblock = self.block 
            self.block = True
            for i in range(len(self.refButtons)):
                btn = self.refButtons[i]
                btn.setCheckable(True)
                btn.setChecked(self.i_active_ref == i)
                typ = _translate('AttachmentEditor',"Reference{i}",None).format(i= str(i+1))
                if self.last_sugr is not None:
                    typestr = self.last_sugr['references_Types']
                    if i < len(typestr):
                        typ = self.attacher.getRefTypeInfo(typestr[i])['UserFriendlyName']
                btn.setText(_translate('AttachmentEditor',"Selecting...",None) if self.i_active_ref == i else typ)
        finally:
            self.block = old_selfblock
            
    def getCurrentMode(self):
        list_widget = self.form.listOfModes
        sel = list_widget.selectedItems()
        if len(sel) == 1:
            if sel[0].data(self.KEYon):
                return str(sel[0].data(self.KEYmode)) # data() returns unicode, which confuses attacher
        # nothing selected in list. Return suggested
        if self.last_sugr is not None:
            if self.last_sugr['message'] == 'OK':
                return self.last_sugr['bestFitMode']
        # no suggested mode. Return current, so it doesn't change
        return self.attacher.Mode
    
    def updatePreview(self):
        new_plm = None
        
        try:
            self.parseAllRefLines()
            self.last_sugr = self.attacher.suggestModes()
            if self.last_sugr['message'] == 'LinkBroken':
                raise ValueError(_translate('AttachmentEditor',"Failed to resolve links. {err}",None).format(err= self.last_sugr['error']))
                
            self.updateListOfModes()
            
            self.attacher.Mode = self.getCurrentMode()
            
            new_plm = self.attacher.calculateAttachedPlacement(self.obj.Placement)
            if new_plm is None:
                self.form.message.setText(_translate('AttachmentEditor',"Not attached",None))
            else:
                self.form.message.setText(    _translate('AttachmentEditor',"Attached with mode {mode}",None)
                                              .format(  mode=   self.attacher.getModeInfo(self.getCurrentMode())['UserFriendlyName']  )    )
                if PlacementsFuzzyCompare(self.obj.Placement, new_plm) == False: 
                    # assign only if placement changed. this avoids touching the object 
                    # when entering and extiting dialog without changing anything
                    self.obj.Placement = new_plm
        except Exception as err:
            self.form.message.setText(_translate('AttachmentEditor',"Error: {err}",None).format(err= err.message))
        
        if new_plm is not None:
            self.form.groupBox_superplacement.setTitle(_translate('AttachmentEditor',"Extra placement:",None))
        else:
            self.form.groupBox_superplacement.setTitle(_translate('AttachmentEditor',"Extra placement (inactive - not attached):",None))

    def cleanUp(self):
        '''stuff that needs to be done when dialog is closed.'''
        Gui.Selection.removeObserver(self)
        self.tv.restore()